"""SQL for the Creditors API. Everything is a read over the masked or named views of ONE run; money is exact (Decimal, serialised as text).

A "relation" is chosen per request from the run's publication state and the caller's access:
  masked  candidate -> cred.v_open_item_candidate        (role cred_verifier)
  masked  live      -> cred.v_open_item                  (role cred_api_reader)
  finance candidate -> cred.v_open_item_named_candidate  (role cred_finance_reader)
  finance live      -> cred.v_open_item_named            (role cred_finance_reader)
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..gold import creditors as _gc, db as _gold

ZERO = Decimal(0)
AGE_BUCKETS = [("D0_30", "0–30"), ("D31_60", "31–60"), ("D61_90", "61–90"), ("D91_180", "91–180"), ("D181_365", "181–365"), ("D365_PLUS", ">365")]
UNCLASSIFIED = ("UNCLASSIFIED", "Unclassified")
DUE_STATES = [("NOT_YET_DUE", "Not yet due"), ("PAST_DUE_OR_DUE_TODAY", "Past due / due today"), ("DUE_UNAVAILABLE", "Due date unavailable"), ("DUE_INVALID", "Invalid due date")]
OVER_90 = ("D91_180", "D181_365", "D365_PLUS")
OVER_180 = ("D181_365", "D365_PLUS")
# Vendor-list cohorts: fixed SQL fragments chosen from this whitelist (never built from request text). They narrow the CREDIT exposure the list is ranked by.
COHORTS = {
    "gt90": "document_age_bucket IN ('D91_180','D181_365','D365_PLUS')",
    "gt180": "document_age_bucket IN ('D181_365','D365_PLUS')",
    "past_due": "due_status = 'PAST_DUE_OR_DUE_TODAY'",
    "not_yet_due": "due_status = 'NOT_YET_DUE'",
    "due_unavailable": "due_status = 'DUE_UNAVAILABLE'",
    "due_invalid": "due_status = 'DUE_INVALID'",
    "unclassified": "document_age_bucket LIKE 'UNCLASSIFIED%'",
    **{b: f"document_age_bucket = '{b}'" for b, _ in AGE_BUCKETS},
}
VENDOR_SORTS = {"credit_outstanding": "credit_outstanding", "debit_balance": "debit_balance", "net": "signed_net", "items": "items",
                "past_due": "past_due_credit", "due_unavailable": "due_unavailable_credit", "oldest": "oldest_credit_age_days", "cohort": "cohort_credit"}


@dataclass(frozen=True)
class Source:
    role: str             # key into db.ROLES
    items: str            # relation holding the open items
    controls: str
    finance: bool
    live: bool


def source_for(run: dict, finance: bool) -> Source:
    if _gold.enabled():
        return Source("finance" if finance else "live", _gc.items(finance), _gc.CONTROLS, finance, True)
    live = run["publication_state"] == "live"
    if finance:
        return Source("finance", "cred.v_open_item_named" if live else "cred.v_open_item_named_candidate", "cred.v_live_controls" if live else "cred.v_control_candidate", True, live)
    return Source("live" if live else "candidate", "cred.v_open_item" if live else "cred.v_open_item_candidate", "cred.v_live_controls" if live else "cred.v_control_candidate", False, live)


def data_state(run: dict) -> str:
    """The state the UI shows. It is decided here, never inferred by the frontend."""
    return {"live": "live", "unpublished": "verified_candidate", "superseded": "superseded", "withdrawn": "withdrawn"}[run["publication_state"]]


def get_run(conn, run_id: str) -> dict | None:
    if _gold.enabled():
        return conn.execute(f"SELECT * FROM {_gc.RUN} WHERE extraction_run_id = %s", (run_id,)).fetchone()
    return conn.execute("SELECT * FROM cred.v_candidate_run WHERE extraction_run_id = %s", (run_id,)).fetchone()


def current_run(conn) -> dict | None:
    """The live run if there is one, otherwise the newest verified candidate."""
    if _gold.enabled():
        return conn.execute(f"SELECT * FROM {_gc.RUN} ORDER BY as_of_date DESC LIMIT 1").fetchone()
    return conn.execute("SELECT * FROM cred.v_candidate_run ORDER BY (publication_state = 'live') DESC, loaded_at DESC LIMIT 1").fetchone()


def list_candidates(conn) -> list[dict]:
    if _gold.enabled():
        return conn.execute(f"SELECT * FROM {_gc.RUN} ORDER BY as_of_date DESC").fetchall()
    return conn.execute("SELECT * FROM cred.v_candidate_run ORDER BY loaded_at DESC").fetchall()


def control_tally(conn, src: Source, run_id: str) -> dict:
    rows = conn.execute(f"SELECT left_layer, right_layer, count(*) AS total, count(*) FILTER (WHERE verdict = 'PASS') AS passed, coalesce(max(abs(variance)), 0) AS max_abs_variance "
                        f"FROM {src.controls} WHERE extraction_run_id = %s GROUP BY 1, 2 ORDER BY 1, 2", (run_id,)).fetchall()
    return {"layers": [{"from": r["left_layer"], "to": r["right_layer"], "controls": r["total"], "passed": r["passed"], "failed": r["total"] - r["passed"], "max_abs_variance": r["max_abs_variance"]} for r in rows],
            "total": sum(r["total"] for r in rows), "passed": sum(r["passed"] for r in rows), "failed": sum(r["total"] - r["passed"] for r in rows)}


def failing_controls(conn, src: Source, run_id: str, limit: int = 50) -> list[dict]:
    return conn.execute(f"SELECT control_id, dimension, left_layer, left_value, right_layer, right_value, variance FROM {src.controls} "
                        f"WHERE extraction_run_id = %s AND verdict <> 'PASS' ORDER BY control_id, dimension LIMIT %s", (run_id, limit)).fetchall()


def summary(conn, src: Source, run_id: str) -> dict:
    r = conn.execute(f"""
        SELECT count(*) AS item_rows, count(DISTINCT vendor_ref) AS vendors,
               count(*) FILTER (WHERE drcr = 'Cr') AS credit_items, count(*) FILTER (WHERE drcr = 'Dr') AS debit_items,
               coalesce(sum(abs(pending)) FILTER (WHERE drcr = 'Cr'), 0) AS credit_outstanding,
               coalesce(sum(abs(pending)) FILTER (WHERE drcr = 'Dr'), 0) AS creditor_debit_balance,
               coalesce(sum(pending), 0) AS signed_net,
               coalesce(sum(abs(pending)) FILTER (WHERE drcr = 'Cr' AND due_status = 'PAST_DUE_OR_DUE_TODAY'), 0) AS past_due_credit,
               count(*) FILTER (WHERE drcr = 'Cr' AND due_status = 'PAST_DUE_OR_DUE_TODAY') AS past_due_items,
               coalesce(sum(abs(pending)) FILTER (WHERE drcr = 'Cr' AND due_status = 'DUE_UNAVAILABLE'), 0) AS due_unavailable_credit,
               count(*) FILTER (WHERE drcr = 'Cr' AND due_status = 'DUE_UNAVAILABLE') AS due_unavailable_items,
               coalesce(sum(abs(pending)) FILTER (WHERE drcr = 'Cr' AND document_age_bucket = ANY(%s)), 0) AS over_90_credit,
               count(*) FILTER (WHERE drcr = 'Cr' AND document_age_bucket = ANY(%s)) AS over_90_items,
               coalesce(sum(abs(pending)) FILTER (WHERE drcr = 'Cr' AND document_age_bucket = ANY(%s)), 0) AS over_180_credit,
               count(*) FILTER (WHERE drcr = 'Cr' AND document_age_bucket = ANY(%s)) AS over_180_items,
               count(DISTINCT vendor_ref) FILTER (WHERE drcr = 'Cr') AS credit_vendors, count(DISTINCT vendor_ref) FILTER (WHERE drcr = 'Dr') AS debit_vendors
        FROM {src.items} WHERE extraction_run_id = %s""", (list(OVER_90), list(OVER_90), list(OVER_180), list(OVER_180), run_id)).fetchone()
    top = conn.execute(f"""
        SELECT vendor_ref, sum(abs(pending)) AS credit FROM {src.items} WHERE extraction_run_id = %s AND drcr = 'Cr' GROUP BY vendor_ref ORDER BY credit DESC, vendor_ref""", (run_id,)).fetchall()
    total = sum((t["credit"] for t in top), ZERO)
    r["credit_concentration"] = {f"top_{n}": (sum((t["credit"] for t in top[:n]), ZERO) / total).quantize(Decimal("0.0001")) if total else ZERO for n in (1, 5, 10, 20)}
    return r


def document_age(conn, src: Source, run_id: str) -> list[dict]:
    rows = conn.execute(f"""
        SELECT document_age_bucket AS bucket, count(*) FILTER (WHERE drcr = 'Cr') AS credit_items, count(*) FILTER (WHERE drcr = 'Dr') AS debit_items,
               coalesce(sum(abs(pending)) FILTER (WHERE drcr = 'Cr'), 0) AS credit_outstanding, coalesce(sum(abs(pending)) FILTER (WHERE drcr = 'Dr'), 0) AS debit_balance,
               coalesce(sum(pending), 0) AS signed_net
        FROM {src.items} WHERE extraction_run_id = %s GROUP BY 1""", (run_id,)).fetchall()
    by = {r["bucket"]: r for r in rows}

    def pack(key, label, rs):
        z = {"credit_items": 0, "debit_items": 0, "credit_outstanding": ZERO, "debit_balance": ZERO, "signed_net": ZERO}
        for r in rs:
            for k in z:
                z[k] += r[k]
        return {"bucket": key, "label": label, **z}

    out = [pack(k, label, [by[k]] if k in by else []) for k, label in AGE_BUCKETS]
    un = [r for k, r in by.items() if k.startswith("UNCLASSIFIED")]
    u = pack(UNCLASSIFIED[0], UNCLASSIFIED[1], un)
    u["reasons"] = [{"reason": r["bucket"].removeprefix("UNCLASSIFIED_"), "credit_items": r["credit_items"], "debit_items": r["debit_items"], "credit_outstanding": r["credit_outstanding"], "debit_balance": r["debit_balance"]} for r in sorted(un, key=lambda x: x["bucket"])]
    return out + [u]


def due_status(conn, src: Source, run_id: str) -> list[dict]:
    rows = conn.execute(f"""
        SELECT due_status AS state, count(*) FILTER (WHERE drcr = 'Cr') AS credit_items, count(*) FILTER (WHERE drcr = 'Dr') AS debit_items,
               coalesce(sum(abs(pending)) FILTER (WHERE drcr = 'Cr'), 0) AS credit_outstanding, coalesce(sum(abs(pending)) FILTER (WHERE drcr = 'Dr'), 0) AS debit_balance,
               coalesce(sum(pending), 0) AS signed_net
        FROM {src.items} WHERE extraction_run_id = %s GROUP BY 1""", (run_id,)).fetchall()
    by = {r["state"]: r for r in rows}
    z = {"credit_items": 0, "debit_items": 0, "credit_outstanding": ZERO, "debit_balance": ZERO, "signed_net": ZERO}
    return [{"state": k, "label": label, **({kk: by[k][kk] for kk in z} if k in by else z)} for k, label in DUE_STATES]


def ledgers(conn, src: Source, run_id: str) -> list[dict]:
    return conn.execute(f"""
        SELECT ledger_code, max(ledger_name) AS ledger_name, count(*) FILTER (WHERE drcr = 'Cr') AS credit_items, count(*) FILTER (WHERE drcr = 'Dr') AS debit_items,
               coalesce(sum(abs(pending)) FILTER (WHERE drcr = 'Cr'), 0) AS credit_outstanding, coalesce(sum(abs(pending)) FILTER (WHERE drcr = 'Dr'), 0) AS debit_balance,
               coalesce(sum(pending), 0) AS signed_net, count(DISTINCT vendor_ref) AS vendors,
               count(DISTINCT vendor_ref) FILTER (WHERE drcr = 'Cr') AS credit_vendors, count(DISTINCT vendor_ref) FILTER (WHERE drcr = 'Dr') AS debit_vendors,
               coalesce(sum(abs(pending)) FILTER (WHERE drcr = 'Cr' AND due_status = 'PAST_DUE_OR_DUE_TODAY'), 0) AS past_due_credit,
               coalesce(sum(abs(pending)) FILTER (WHERE drcr = 'Cr' AND due_status = 'DUE_UNAVAILABLE'), 0) AS due_unavailable_credit
        FROM {src.items} WHERE extraction_run_id = %s GROUP BY ledger_code ORDER BY ledger_code""", (run_id,)).fetchall()


def vendors(conn, src: Source, run_id: str, *, ledger_code=None, party_class=None, q=None, vendor_ref=None, cohort=None, sort="credit_outstanding", descending=True, limit=100, offset=0) -> dict:
    cond = COHORTS.get(cohort) if cohort else None
    if cohort and cond is None:
        raise ValueError(f"unknown cohort {cohort!r}")
    cohort_col = f", coalesce(sum(abs(pending)) FILTER (WHERE drcr = 'Cr' AND {cond}), 0) AS cohort_credit" if cond else ""
    having = " HAVING coalesce(sum(abs(pending)) FILTER (WHERE drcr = 'Cr' AND " + cond + "), 0) > 0" if cond else ""
    if cond and sort == "credit_outstanding":
        sort = "cohort"
    if sort == "cohort" and not cond:
        sort = "credit_outstanding"
    where, params = ["extraction_run_id = %s"], [run_id]
    for col, val in (("ledger_code", ledger_code), ("party_class", party_class), ("vendor_ref", vendor_ref)):
        if val:
            where.append(f"{col} = %s")
            params.append(val)
    if q and src.finance:
        where.append("vendor_name ILIKE %s")
        params.append(f"%{q}%")
    w = " AND ".join(where)
    sort_col = VENDOR_SORTS.get(sort) or ("vendor_name" if sort == "name" and src.finance else "credit_outstanding")
    direction = "DESC" if descending else "ASC"
    extra_group = ", vendor_name, slid, sub_ledger_code, credit_days" if src.finance else ""
    extra_cols = ", vendor_name, slid, sub_ledger_code, credit_days" if src.finance else ""
    rows = conn.execute(f"""
        SELECT vendor_ref{extra_cols}, max(party_class) AS party_class, max(party_class_type) AS party_class_type,
               array_agg(DISTINCT ledger_code ORDER BY ledger_code) AS ledger_codes,
               count(*) AS items, count(*) FILTER (WHERE drcr = 'Cr') AS credit_items, count(*) FILTER (WHERE drcr = 'Dr') AS debit_items,
               coalesce(sum(abs(pending)) FILTER (WHERE drcr = 'Cr'), 0) AS credit_outstanding, coalesce(sum(abs(pending)) FILTER (WHERE drcr = 'Dr'), 0) AS debit_balance,
               coalesce(sum(pending), 0) AS signed_net,
               coalesce(sum(abs(pending)) FILTER (WHERE drcr = 'Cr' AND due_status = 'PAST_DUE_OR_DUE_TODAY'), 0) AS past_due_credit,
               coalesce(sum(abs(pending)) FILTER (WHERE drcr = 'Cr' AND due_status = 'DUE_UNAVAILABLE'), 0) AS due_unavailable_credit,
               max(document_age_days) FILTER (WHERE drcr = 'Cr') AS oldest_credit_age_days{cohort_col}
        FROM {src.items} WHERE {w} GROUP BY vendor_ref{extra_group}{having}
        ORDER BY {sort_col} {direction} NULLS LAST, vendor_ref LIMIT %s OFFSET %s""", params + [limit, offset]).fetchall()
    tot = conn.execute(f"SELECT count(DISTINCT vendor_ref) AS vendors, coalesce(sum(abs(pending)) FILTER (WHERE drcr = 'Cr'), 0) AS credit_outstanding, "
                       f"coalesce(sum(abs(pending)) FILTER (WHERE drcr = 'Dr'), 0) AS debit_balance, coalesce(sum(pending), 0) AS signed_net FROM {src.items} WHERE {w}", params).fetchone()
    if cond:
        tot = conn.execute(f"SELECT count(*) AS vendors, coalesce(sum(c), 0) AS cohort_credit FROM (SELECT sum(abs(pending)) FILTER (WHERE drcr = 'Cr' AND {cond}) AS c FROM {src.items} WHERE {w} GROUP BY vendor_ref HAVING coalesce(sum(abs(pending)) FILTER (WHERE drcr = 'Cr' AND {cond}), 0) > 0) t", params).fetchone() | {k: tot[k] for k in ("credit_outstanding", "debit_balance", "signed_net")}
    all_credit = conn.execute(f"SELECT coalesce(sum(abs(pending)) FILTER (WHERE drcr = 'Cr'), 0) AS c FROM {src.items} WHERE extraction_run_id = %s", (run_id,)).fetchone()["c"]
    refs = [r["vendor_ref"] for r in rows]
    age, due = {}, {}
    if refs:
        for r in conn.execute(f"SELECT vendor_ref, document_age_bucket AS b, sum(abs(pending)) AS a FROM {src.items} WHERE extraction_run_id = %s AND drcr = 'Cr' AND vendor_ref = ANY(%s) GROUP BY 1, 2", (run_id, refs)):
            key = "UNCLASSIFIED" if r["b"].startswith("UNCLASSIFIED") else r["b"]
            age.setdefault(r["vendor_ref"], {}).setdefault(key, ZERO)
            age[r["vendor_ref"]][key] += r["a"]
        for r in conn.execute(f"SELECT vendor_ref, due_status AS s, sum(abs(pending)) AS a FROM {src.items} WHERE extraction_run_id = %s AND drcr = 'Cr' AND vendor_ref = ANY(%s) GROUP BY 1, 2", (run_id, refs)):
            due.setdefault(r["vendor_ref"], {})[r["s"]] = r["a"]
    for r in rows:
        r["share_of_credit"] = (r["credit_outstanding"] / all_credit).quantize(Decimal("0.000001")) if all_credit else ZERO
        r["credit_by_document_age"] = {k: age.get(r["vendor_ref"], {}).get(k, ZERO) for k, _ in AGE_BUCKETS + [UNCLASSIFIED]}
        r["credit_by_due_status"] = {k: due.get(r["vendor_ref"], {}).get(k, ZERO) for k, _ in DUE_STATES}
    return {"total": tot, "returned": len(rows), "limit": limit, "offset": offset, "vendors": rows}


def items(conn, src: Source, run_id: str, vendor_ref: str, *, drcr=None, bucket=None, due=None, limit=500, offset=0) -> dict:
    where, params = ["extraction_run_id = %s", "vendor_ref = %s"], [run_id, vendor_ref]
    if drcr in ("Cr", "Dr"):
        where.append("drcr = %s")
        params.append(drcr)
    if bucket:
        where.append("(document_age_bucket = %s OR (%s = 'UNCLASSIFIED' AND document_age_bucket LIKE 'UNCLASSIFIED%%'))")
        params += [bucket, bucket]
    if due:
        where.append("due_status = %s")
        params.append(due)
    w = " AND ".join(where)
    cols = ("source_row_key AS item_ref, ledger_code, ledger_name, drcr, amount, adjusted, pending, document_type, due_date_basis, document_date, due_date, entry_date, "
            "document_age_days, document_age_bucket, overdue_days, due_status, date_quality_status, classification_status")
    if src.finance:
        cols += ", document_code, document_no, document_initial, ref_no, ref_date, created_by_site, sub_ledger_code"
    else:
        cols = cols.replace("source_row_key AS item_ref", "item_ref")
    rows = conn.execute(f"SELECT {cols} FROM {src.items} WHERE {w} ORDER BY document_date NULLS LAST, 1 LIMIT %s OFFSET %s", params + [limit, offset]).fetchall()
    n = conn.execute(f"SELECT count(*) AS n FROM {src.items} WHERE {w}", params).fetchone()["n"]
    return {"total_items": n, "returned": len(rows), "limit": limit, "offset": offset, "items": rows}
