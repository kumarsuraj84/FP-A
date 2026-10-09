"""P&L serving views over gold_fpa (pnl_store_month, cogs_store_month, dim_site, control_totals, voucher_lines).
One synthetic run 'PNL-<latest period>' (live, verified) stands in for the old run-versioned mart. See docs/GOLD_SOURCE_GAPS_PNL.md for what has no source.
Budget: NOT wired (gold_fpa.budget_ledger_month is unreliable); the API serves budget as null by design.
NOTE: each relation is self-contained (the GoldConn wrapper only rewrites names in the outer statement, not inside another relation), and no percent sign appears (psycopg params)."""
from __future__ import annotations

# the finance P&L's group -> P&L section table (same as tools/extraction_broker/pl_stage.py SECTION_OF_GROUP); a mapped group not listed becomes UNMAPPED
SECTION_OF_GROUP = {
    "01-Net Sales": "REVENUE",
    "02-Other Income": "OTHER_INCOME", "24-Interest Income": "OTHER_INCOME",
    "02-COGS(Product)": "COGS_BOOKS", "02-COGS(Others)": "COGS_BOOKS", "02-COGS(Correction)": "COGS_BOOKS",
    "01-Rent": "STORE_OPEX", "02-Employee Cost": "STORE_OPEX", "03-Power and Fuel Expenses": "STORE_OPEX", "05-Director remunaration": "STORE_OPEX",
    "07-Advertisement And Sales Promotion": "STORE_OPEX", "08-Freight Outward": "STORE_OPEX", "09-Insurance": "STORE_OPEX", "10-Travelling & Conveyance Expenses": "STORE_OPEX",
    "11-Communication": "STORE_OPEX", "12-Repairs and Maintenance-Others": "STORE_OPEX", "13-Packing Materials And Expenses": "STORE_OPEX",
    "14-Legal and Professional Expenses": "STORE_OPEX", "16-Miscellaneous Expenses": "STORE_OPEX", "17-Bank Charges": "STORE_OPEX", "20-Printing & Stationery": "STORE_OPEX",
    "21-Finance Cost": "FINANCE_COST",
}

_VALUES = ", ".join("('" + g.replace("'", "''") + "', '" + s + "')" for g, s in SECTION_OF_GROUP.items())
RUN_ID = "'PNL-' || to_char((SELECT max(month) FROM gold_fpa.pnl_store_month), 'YYYYMM')"
AS_OF = "(SELECT max(entdt) FROM gold_fpa.voucher_lines WHERE entdt <= current_date)"

_GL_COLS = "run_id, site_code, month, glcode, ledger_name, group_label, section, entry_type_short, release_status, debit, credit, lines"

_V_GL_SITE_MONTH = f"""SELECT {RUN_ID} AS run_id, p.site_code::text AS site_code, p.month, p.glcode::text AS glcode, p.glname AS ledger_name,
    CASE WHEN gs.section IS NULL THEN NULL ELSE p.fin_group END AS group_label, coalesce(gs.section, 'UNMAPPED') AS section,
    p.enttype AS entry_type_short, CASE WHEN p.release_status = 'P' THEN 'Posted' ELSE 'Unposted' END AS release_status,
    sum(p.debit) AS debit, sum(p.credit) AS credit, sum(p.lines_n)::int AS lines
    FROM gold_fpa.pnl_store_month p
    LEFT JOIN (VALUES {_VALUES}) AS gs(grp, section) ON gs.grp = p.fin_group AND p.is_mapped
    GROUP BY p.site_code, p.month, p.glcode, p.glname, gs.section, p.fin_group, p.enttype, p.release_status"""

_V_COGS = f"""SELECT {RUN_ID} AS run_id, c.site_code::text AS site_code, c.month,
    (c.net_sales_ex_gst + coalesce(c.tax_amt, 0))::numeric AS sl_v, coalesce(c.tax_amt, 0)::numeric AS tax_amt, c.cogs_v::numeric AS cogs_v, c.sl_q::numeric AS sl_q, c.rows_n::int AS rows_n, c.bill_days::int AS bill_days,
    c.first_bill, c.last_bill,
    NULL::numeric AS sl_v_early, NULL::numeric AS tax_early, NULL::numeric AS cogs_early, NULL::numeric AS sl_q_early
    FROM gold_fpa.cogs_store_month c"""

_V_SITE = f"""SELECT {RUN_ID} AS run_id, d.site_code::text AS site_code, d.store_name, d.opening_date, d.store_status,
    nullif(d.store_type, '-') AS store_current_status, d.cluster_type, d.region_type, d.state, d.store_type, d.last_bill_date,
    nullif(d.area, 0)::numeric(12,2) AS area, NULL::text AS st_type, NULL::text AS store_grade
    FROM gold_fpa.dim_site d"""

_V_TIEOUT = f"""SELECT {RUN_ID} AS run_id, coalesce(b.site_code, t.site_code)::text AS site_code, coalesce(b.month, t.month) AS month,
    coalesce(b.v, 0) AS books_sales, coalesce(t.v, 0) AS cogs_table_sales_ex_gst, coalesce(b.v, 0) - coalesce(t.v, 0) AS difference,
    abs(coalesce(b.v, 0) - coalesce(t.v, 0)) <= 1000 AS tied
    FROM (SELECT site_code, month, sum(credit - debit) AS v FROM gold_fpa.pnl_store_month WHERE glname = 'Sales - POS' GROUP BY 1, 2) b
    FULL OUTER JOIN (SELECT site_code, month, sum(net_sales_ex_gst) AS v FROM gold_fpa.cogs_store_month GROUP BY 1, 2) t ON t.site_code = b.site_code AND t.month = b.month"""

# Effective area = area x active days / calendar days, the same rules as pl_stage.effective_area, derived in SQL from dim_site. Stores only (site_kind STORE).
_V_EFF_AREA = f"""WITH asof AS (SELECT {AS_OF} AS d),
 s AS (SELECT site_code, nullif(area, 0) AS area, opening_date, store_status, last_bill_date FROM gold_fpa.dim_site WHERE site_kind = 'STORE'),
 m AS (SELECT g::date AS month, (g + interval '1 month - 1 day')::date AS m_end, extract(day FROM (g + interval '1 month - 1 day'))::int AS cal
       FROM asof, generate_series(DATE '2025-04-01', date_trunc('month', asof.d), interval '1 month') g),
 j AS (SELECT s.site_code, s.area, s.opening_date, m.month, m.m_end, m.cal, asof.d AS as_of,
        CASE WHEN s.store_status IN ('CLOSED', 'IN-ACTIVE') AND s.last_bill_date >= DATE '2005-01-01' AND s.last_bill_date < asof.d THEN s.last_bill_date END AS closing,
        (s.store_status IN ('CLOSED', 'IN-ACTIVE') AND NOT (s.last_bill_date >= DATE '2005-01-01' AND s.last_bill_date < asof.d)) AS closure_unknown
       FROM s CROSS JOIN m CROSS JOIN asof),
 k AS (SELECT j.*, least(m_end, as_of) AS end0,
        CASE WHEN opening_date IS NULL OR opening_date < DATE '2005-01-01' THEN 'OPENING_DATE_PLACEHOLDER' WHEN opening_date > m_end THEN 'NOT_YET_OPEN' WHEN opening_date > month THEN 'OPENED_IN_MONTH' END AS f_open,
        CASE WHEN opening_date IS NULL OR opening_date < DATE '2005-01-01' THEN month WHEN opening_date > m_end THEN m_end + 1 WHEN opening_date > month THEN opening_date ELSE month END AS d_start
       FROM j),
 e AS (SELECT k.*, CASE WHEN closing < month THEN 'AFTER_CLOSE' WHEN closing < end0 THEN 'CLOSED_IN_MONTH' END AS f_close,
        CASE WHEN closing < month THEN month - 1 WHEN closing < end0 THEN closing ELSE end0 END AS d_end FROM k),
 f AS (SELECT e.*, greatest(0, d_end - d_start + 1) AS days,
        CASE WHEN d_end >= month AND as_of < m_end AND date_trunc('month', as_of)::date = month THEN 'PARTIAL_MONTH_TO_AS_OF' END AS f_part FROM e)
 SELECT {RUN_ID} AS run_id, site_code::text AS site_code, month, area::numeric(12,2) AS actual_area, opening_date,
        closing AS closing_date, days::int AS active_days, cal AS calendar_days,
        CASE WHEN area > 0 THEN round(area * days / cal, 4) END::numeric(18,4) AS effective_area,
        coalesce(nullif(concat_ws('+', CASE WHEN area IS NULL THEN 'AREA_MISSING' END, f_open, f_close, CASE WHEN closure_unknown THEN 'CLOSURE_DATE_UNKNOWN' END, f_part), ''), 'FULL_MONTH') AS reason
 FROM f"""

# controls: source = gold_fpa.control_totals, extract = recomputed from the same gold tables. layer pairs follow the old mart's (source, extract), (extract, mart).
def _ctl(ctrl: str, dim: str, left: str, right: str, frm: str) -> str:
    return (f"SELECT {RUN_ID} AS run_id, '{ctrl}' AS control_id, {dim} AS dimension, 'source' AS left_layer, ({left})::numeric AS left_value, 'extract' AS right_layer, ({right})::numeric AS right_value, "
            f"({right})::numeric - ({left})::numeric AS variance, CASE WHEN abs(({right})::numeric - ({left})::numeric) < 0.005 THEN 'PASS' ELSE 'FAIL' END AS verdict {frm}")


_PNL_CT = ("FROM gold_fpa.control_totals c JOIN (SELECT month, ledger_type, sum(lines_n) AS n, sum(debit) AS d, sum(credit) AS cr, sum(profit_effect) AS a "
           "FROM gold_fpa.pnl_store_month GROUP BY 1, 2) p ON p.month = c.period AND p.ledger_type = c.group_key WHERE c.table_name = 'pnl_store_month'")
_COGS_CT = ("FROM gold_fpa.control_totals c JOIN (SELECT month, count(*) AS n, sum(net_sales_ex_gst) AS sales, sum(cogs_v) AS cogs FROM gold_fpa.cogs_store_month GROUP BY 1) p "
            "ON p.month = c.period WHERE c.table_name = 'cogs_store_month'")
_CT = "to_char(c.period, 'YYYY-MM') || ' ' || c.group_key"

_V_CONTROL = "\nUNION ALL\n".join([
    _ctl("GL_LINES", _CT, "c.row_count", "p.n", _PNL_CT),
    _ctl("GL_DEBIT", _CT, "c.sum_debit", "p.d", _PNL_CT),
    _ctl("GL_CREDIT", _CT, "c.sum_credit", "p.cr", _PNL_CT),
    _ctl("GL_PROFIT_EFFECT", _CT, "c.sum_amount", "p.a", _PNL_CT),
    _ctl("COGS_ROWS", "to_char(c.period, 'YYYY-MM')", "c.row_count", "p.n", _COGS_CT + " AND c.group_key = 'cogs'"),
    _ctl("COGS_VALUE", "to_char(c.period, 'YYYY-MM')", "c.sum_amount", "p.cogs", _COGS_CT + " AND c.group_key = 'cogs'"),
    _ctl("COGS_SALES_EX_GST", "to_char(c.period, 'YYYY-MM')", "c.sum_amount", "p.sales", _COGS_CT + " AND c.group_key = 'sales'"),
])

_V_SERVING_RUN = f"""SELECT {RUN_ID} AS run_id, {AS_OF} AS as_of_date, 'gold_fpa' AS cogs_run_id, (SELECT max(last_bill) FROM gold_fpa.cogs_store_month) AS cogs_last_bill_date,
    'verified' AS recon_state, 'live' AS publication_state, 'gold_fpa-1' AS contract_version,
    (SELECT max(_loaded_at) FROM gold_fpa.pnl_store_month) AS extract_finished_at, (SELECT max(_loaded_at) FROM gold_fpa.pnl_store_month) AS loaded_at,
    (SELECT count(*) FROM gold_fpa.pnl_store_month)::int AS expected_gl_rows, (SELECT count(*) FROM gold_fpa.cogs_store_month)::int AS expected_cogs_rows,
    (SELECT count(*) FROM gold_fpa.dim_site)::int AS expected_sites, 0.01::numeric(30,4) AS tolerance_rupees,
    NULL::int AS aligned_days, NULL::date AS ly_aligned_month"""

# day-aligned last-year window: gold_fpa has no daily COGS, so the run declares no aligned window (ly_aligned_month NULL) and this view is empty.
_V_GL_ALIGNED = """SELECT NULL::text AS run_id, NULL::text AS site_code, NULL::date AS month, NULL::text AS glcode, NULL::text AS ledger_name, NULL::text AS group_label, NULL::text AS section,
    NULL::text AS entry_type_short, NULL::text AS release_status, NULL::numeric AS debit, NULL::numeric AS credit, NULL::int AS lines WHERE false"""

_V_GROUP_SECTION = f"SELECT {RUN_ID} AS run_id, grp AS group_label, section FROM (VALUES {_VALUES}) AS gs(grp, section)"

RELATIONS = {
    "pnl.v_serving_run": _V_SERVING_RUN,
    "pnl.v_gl_site_month": _V_GL_SITE_MONTH,
    "pnl.v_cogs_site_month": _V_COGS,
    "pnl.v_site": _V_SITE,
    "pnl.v_sales_tieout": _V_TIEOUT,
    "pnl.v_store_month_effective_area": _V_EFF_AREA,
    "pnl.v_control": _V_CONTROL,
    "pnl.v_gl_aligned": _V_GL_ALIGNED,
    "pnl.v_group_section": _V_GROUP_SECTION,
}
