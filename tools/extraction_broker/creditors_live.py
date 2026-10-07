"""
creditors_live_01: the Creditors outstanding position read from the LIVE SSRK posting tables instead of the temporary MISRETAIL cube T$FINOTSD_533.

It reuses the verified pilot's queries unchanged (same dataset names, same columns, same controls, so creditors_stage and the mart loader see the same shape) by pointing them at an
inline view that rebuilds the cube's rows from SSRK:
  FINPOST (the postings) + FINGL (ledger names) + FINSL / ADMCLS (vendors, classes, due-date basis) + V_FIN (the display document number, type and initial) + ADMSITE (creating site)
Mapping (proved against the 05 Oct cube, see docs/ssrk/SSRK_META_DISCOVERY.md, parts 8 and 9):
  DOCUMENT_CODE = FINPOST.ENTCODE; AMOUNT = DAMOUNT - CAMOUNT; ADJUSTED = ADJAMT (signed against the item, empty when 0); PENDING = AMOUNT + ADJUSTED; open = PENDING <> 0
  DOCUMENT_DATE = ENTDT when the vendor's due-date basis is E (Entry Date), else DOCDT (ENTDT when there is none); DUE_DATE = DUEDT; REF_DATE = DOCDT; ENTRY_DATE = ENTDT
  DUE_DATE_BASIS: D = 'Document Date', E = 'Entry Date'; PARTY_CLASS_TYPE from ADMCLS.CLSTYPE (S Supplier, T Transporter, O Others, D none)
AS-OF: the live tables hold only the CURRENT position, so the as-of date must be today; the moment of the extraction is recorded by the broker. The pre / post controls (pilot c1..c3)
detect any posting made while the extract runs. Read only: SELECT through the broker, guard-checked, capped.
"""
from __future__ import annotations

from datetime import date

import packages
from packages import Dataset

_OPEN_LEDGERS = ", ".join(str(c) for c in packages.CREDITOR_LEDGERS)

_SITE_NAME = "(SELECT code AS code, name AS name FROM SSRK.ADMSITE)"


# The cube names a few document types differently from V_FIN. This dictionary was read off the 11,604 items present in BOTH the verified 05 Oct cube run and the live extract
# (every V_FIN pair maps to exactly one cube pair, none ambiguous); every other pair passes through unchanged.
_LABELS = {
    ("Journal", "JN"): ("AR/AP Journal", "IJ"), ("Sale Invoice", "SAL"): ("Sale Invoice", "SI"), ("Sale Return", "SRT"): ("Sale Return", "SR"),
    ("Sale Service Invoice", "SSM"): ("Sale Service Invoice", "SS"), ("Service Debit Note", "PD"): ("Service Debit Note", "PS"),
    ("TDS Reversal Journal", "JD"): ("TDS Reversal", "TDS"), ("Voucher (AR/AP)", "VP"): ("AR/AP Voucher", "VP"),
}


def _label_case(idx: int, raw: str) -> str:
    whens = " ".join(f"WHEN TRIM(v.type) = '{k[0]}' AND TRIM(v.initial_type) = '{k[1]}' THEN '{v[idx]}'" for k, v in _LABELS.items())
    return f"CASE {whens} ELSE {raw} END"


_TYPE_CASE = _label_case(0, "TRIM(v.type)")
_INITIAL_CASE = _label_case(1, "TRIM(v.initial_type)")


def _cube_view(as_of: str, *, open_only: bool, full: bool) -> str:
    """The cube's rows rebuilt from SSRK. `full` adds V_FIN (document number / type / initial) and the creating site: needed only for the open items themselves."""
    adj = "CASE WHEN NVL(p.adjamt, 0) = 0 THEN NULL WHEN NVL(p.damount, 0) > NVL(p.camount, 0) THEN -p.adjamt ELSE p.adjamt END"
    amt = "(NVL(p.damount, 0) - NVL(p.camount, 0))"
    pend = f"({amt} + NVL({adj}, 0))"
    basis = "CASE fs.due_date_basis WHEN 'E' THEN 'Entry Date' WHEN 'D' THEN 'Document Date' END"
    docdate = "CASE WHEN fs.due_date_basis = 'E' THEN p.entdt ELSE NVL(p.docdt, p.entdt) END"
    cols = (f"DATE '{as_of}' AS report_date, p.entcode AS document_code, p.slcode AS sub_ledger_code, p.glcode AS ledger_code, "
            f"{docdate} AS document_date, p.duedt AS due_date, {basis} AS due_date_basis, p.docdt AS ref_date, p.entdt AS entry_date, "
            f"CASE WHEN NVL(p.damount, 0) > NVL(p.camount, 0) THEN 'Dr' ELSE 'Cr' END AS drcr, {amt} AS amount, {adj} AS adjusted, {pend} AS pending")
    frm = "FROM SSRK.FINPOST p LEFT JOIN SSRK.FINSL fs ON fs.slcode = p.slcode"
    if full:
        cols += (f", TRIM(v.display_docno) AS document_no, {_TYPE_CASE} AS document_type, {_INITIAL_CASE} AS document_initial, "
                 "CASE WHEN v.ref_no IS NULL THEN NULL WHEN v.ref_dt IS NULL THEN v.ref_no ELSE v.ref_no || ' (' || TO_CHAR(v.ref_dt, 'DD/MM/YY') || ')' END AS ref_no, st.name AS created_by_site")
        frm += " JOIN SSRK.V_FIN v ON v.posting_code = p.postcode LEFT JOIN SSRK.ADMSITE st ON st.code = p.admsite_code_owner"
    where = f"p.entdt >= DATE '2016-01-01' AND p.glcode IN ({_OPEN_LEDGERS})"
    if open_only:
        where += f" AND {pend} <> 0"
    return f"(SELECT {cols} {frm} WHERE {where})"


_LEDGER_VIEW = "(SELECT glcode AS glcode, glname AS glname FROM SSRK.FINGL)"
_VENDOR_VIEW = ("(SELECT f.slcode AS slcode, f.slid AS slid, f.slname AS sl_name, k.clsname AS sl_class, "
                "CASE k.clstype WHEN 'S' THEN 'Supplier' WHEN 'T' THEN 'Transporter' WHEN 'O' THEN 'Others' WHEN 'D' THEN NULL ELSE k.clstype END AS sl_class_type, "
                "f.crdays AS credit_days, CASE f.ext WHEN 'Y' THEN 'Yes' ELSE 'No' END AS is_extinct FROM SSRK.FINSL f LEFT JOIN SSRK.ADMCLS k ON k.clscode = f.clscode)")


def _retarget(sql: str, view: str) -> str:
    return sql.replace(packages._T, view).replace(packages._PL, _LEDGER_VIEW).replace(packages._PS, _VENDOR_VIEW)


def datasets(as_of: str) -> tuple[Dataset, ...]:
    light_open = _cube_view(as_of, open_only=True, full=False)
    full_open = _cube_view(as_of, open_only=True, full=True)
    light_all = _cube_view(as_of, open_only=False, full=False)
    c1, c2, c3 = (_retarget(s, light_open) for s in (packages.PILOT_C1_SQL, packages.PILOT_C2_SQL, packages.PILOT_C3_SQL))
    e1 = _retarget(packages.PILOT_E1_SQL, full_open)
    e2 = _retarget(packages.PILOT_E2_SQL, light_all)
    return (
        Dataset("c1_source_control_pre", "extract", "Source control before the extract: ledger x Dr/Cr x Document Age x Due Status, computed in Oracle from the live postings.", sql=c1, role="control_pre"),
        Dataset("c2_vendor_control_pre", "extract", "Source control before the extract: distinct vendors in total, per ledger, per Dr/Cr.", sql=c2, role="control_pre"),
        Dataset("c3_snapshot_control_pre", "extract", "Source control before the extract: rows, key uniqueness, nulls, join coverage.", sql=c3, role="control_pre"),
        Dataset("e1_open_items", "extract", "The extract: one row per open item of the four creditor ledgers (PENDING <> 0), live.", sql=e1, role="extract"),
        Dataset("e2_identity_all_rows", "extract", "Identity and PENDING of every row in the four ledgers, open or settled (identity-stability evidence only).", sql=e2, role="identity"),
        Dataset("c1_source_control_post", "extract", "The same source control again after the extract.", sql=c1, role="control_post"),
        Dataset("c2_vendor_control_post", "extract", "The same vendor control again after the extract.", sql=c2, role="control_post"),
        Dataset("c3_snapshot_control_post", "extract", "The same snapshot control again after the extract.", sql=c3, role="control_post"),
    )


def meta(as_of: str) -> dict:
    base = packages.PACKAGE_META["creditors_pilot_01"]
    contract = {**base["contract"], "contract_version": "creditors-live-1.0",
                "scope": {"source_object": "SSRK.FINPOST (live) + SSRK.V_FIN + SSRK.FINSL + SSRK.ADMCLS + SSRK.FINGL + SSRK.ADMSITE", "ledger_codes": list(packages.CREDITOR_LEDGERS),
                          "open_predicate": "PENDING <> 0", "as_of_source": "the extraction day (live tables hold only the current position)"},
                "as_of": as_of}
    return {"halt_on_failure": True, "contract": contract}


def configure_live(as_of: str, today: date | None = None) -> None:
    try:
        d = date.fromisoformat(as_of)
    except ValueError:
        raise ValueError("the as-of date must be a real date written YYYY-MM-DD") from None
    if d.isoformat() != as_of:
        raise ValueError("the as-of date must be written YYYY-MM-DD")
    if d != (today or date.today()):
        raise ValueError("creditors_live_01 reads the LIVE position, so the as-of date must be today; a past position cannot be produced from live tables")
    packages.PACKAGES["creditors_live_01"] = datasets(as_of)
    packages.PACKAGE_META["creditors_live_01"] = meta(as_of)


configure_live(date.today().isoformat())
