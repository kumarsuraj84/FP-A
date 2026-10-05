"""
entry_identity_probe_01: which columns make a register entry (and its lines) unique? Aggregate COUNTS only: no row values, no text, no names.

Evidence behind it: the first real entry staging run found the same (SITECODE, ENTRY_TYPE_SHORT, ENTRY_NO) used by different creating warehouses on different dates, and the same SEQ
repeated within an entry. This probe measures, over the FY26-27 site register, how many identities collapse under each candidate key, so the identity can be redefined on evidence.
Registered into the broker's package table from here (the table itself lives in packages.py).
"""
from __future__ import annotations

import packages
from packages import Dataset

_REG = packages._ENTRY_SITE
_FYS = "DATE '2026-04-01'"
_A = "r.sitecode, r.entry_type_short, r.entry_no"
CANDIDATES = {
    "A_site_type_no": _A,
    "B_plus_admou": f"{_A}, r.admou_code",
    "C_plus_creator": f"{_A}, r.created_by_site",
    "D_plus_admou_creator": f"{_A}, r.admou_code, r.created_by_site",
}


def _profile() -> str:
    return ("SELECT COUNT(*) AS lines_total, COUNT(DISTINCT r.admou_code) AS distinct_admou, COUNT(*) - COUNT(r.admou_code) AS null_admou, "
            "COUNT(DISTINCT r.cube_code) AS distinct_cube, COUNT(DISTINCT r.created_by_site) AS distinct_creator, COUNT(*) - COUNT(r.created_by_site) AS null_creator, "
            "COUNT(DISTINCT r.sitecode) AS distinct_sitecode "
            f"FROM {_REG} r WHERE r.entry_date >= {_FYS} FETCH FIRST 5 ROWS ONLY")


def _identity(cols: str, tag: str) -> str:
    """One row: how many identities exist under this key, and how many of them still mix several dates / creators / repeat a line key."""
    return (f"SELECT '{tag}' AS candidate, COUNT(*) AS identities, SUM(CASE WHEN nd > 1 THEN 1 ELSE 0 END) AS ids_multi_date, SUM(CASE WHEN nc > 1 THEN 1 ELSE 0 END) AS ids_multi_creator, "
            "SUM(CASE WHEN nl > nk THEN 1 ELSE 0 END) AS ids_repeated_line_key, SUM(nl) AS lines_total "
            "FROM (SELECT COUNT(DISTINCT r.entry_date) AS nd, COUNT(DISTINCT r.created_by_site) AS nc, COUNT(*) AS nl, "
            "COUNT(DISTINCT TO_CHAR(r.seq) || '|' || TO_CHAR(r.entry_glcode) || '|' || TO_CHAR(r.entry_slcode)) AS nk "
            f"FROM {_REG} r WHERE r.entry_date >= {_FYS} GROUP BY {cols}) FETCH FIRST 5 ROWS ONLY")


ENTRY_IDENTITY_PROBE_01: tuple[Dataset, ...] = (
    Dataset("p0_profile", "extract", "Distinct counts and nulls of the candidate key columns over the FY26-27 register.", sql=_profile()),
    *[Dataset(f"p1_identity_{tag}", "extract", f"Identities under candidate key {tag}: how many still mix dates, creators, or repeat a line key.", sql=_identity(cols, tag)) for tag, cols in CANDIDATES.items()],
)
packages.PACKAGES["entry_identity_probe_01"] = ENTRY_IDENTITY_PROBE_01


_C = f"{_A}, r.created_by_site"


def _c_split() -> str:
    """Under key C: do the identities that still span several dates belong to the missing-creator group, and how far apart are their dates?"""
    return ("SELECT COUNT(*) AS identities, SUM(isnull) AS ids_null_creator, SUM(CASE WHEN nd > 1 THEN 1 ELSE 0 END) AS multi_date, "
            "SUM(CASE WHEN nd > 1 AND isnull = 1 THEN 1 ELSE 0 END) AS multi_date_null_creator, SUM(CASE WHEN nd > 1 AND isnull = 0 THEN 1 ELSE 0 END) AS multi_date_with_creator, "
            "SUM(CASE WHEN nd > 1 AND span <= 31 THEN 1 ELSE 0 END) AS multi_date_within_31d, SUM(CASE WHEN nd > 1 AND span > 31 THEN 1 ELSE 0 END) AS multi_date_over_31d "
            "FROM (SELECT COUNT(DISTINCT r.entry_date) AS nd, MAX(CASE WHEN r.created_by_site IS NULL THEN 1 ELSE 0 END) AS isnull, MAX(r.entry_date) - MIN(r.entry_date) AS span "
            f"FROM {_REG} r WHERE r.entry_date >= {_FYS} GROUP BY {_C}) FETCH FIRST 5 ROWS ONLY")


def _e_identity() -> str:
    """Key E = A + creating site + entry date: identities, and whether lines still repeat their line key."""
    return ("SELECT COUNT(*) AS identities, SUM(CASE WHEN nl > nk THEN 1 ELSE 0 END) AS ids_repeated_line_key, SUM(nl) AS lines_total "
            "FROM (SELECT COUNT(*) AS nl, COUNT(DISTINCT TO_CHAR(r.seq) || '|' || TO_CHAR(r.entry_glcode) || '|' || TO_CHAR(r.entry_slcode)) AS nk "
            f"FROM {_REG} r WHERE r.entry_date >= {_FYS} GROUP BY {_C}, r.entry_date) FETCH FIRST 5 ROWS ONLY")


def _line_repeats() -> str:
    """Under key E, for every (seq, ledger, sub-ledger) that has more than one line: how many, and are they exact copies (same debit and credit)?"""
    return ("SELECT COUNT(*) AS repeated_line_keys, SUM(n) AS lines_in_repeated_keys, SUM(CASE WHEN same = 1 THEN 1 ELSE 0 END) AS keys_with_identical_amounts, "
            "SUM(CASE WHEN same = 0 THEN 1 ELSE 0 END) AS keys_with_different_amounts, MAX(n) AS max_lines_per_key "
            "FROM (SELECT COUNT(*) AS n, CASE WHEN MIN(r.debit) = MAX(r.debit) AND MIN(r.credit) = MAX(r.credit) THEN 1 ELSE 0 END AS same "
            f"FROM {_REG} r WHERE r.entry_date >= {_FYS} GROUP BY {_C}, r.entry_date, r.seq, r.entry_glcode, r.entry_slcode HAVING COUNT(*) > 1) FETCH FIRST 5 ROWS ONLY")


ENTRY_IDENTITY_PROBE_02: tuple[Dataset, ...] = (
    Dataset("q1_key_c_split", "extract", "Key C identities that still span several dates: missing-creator group or not, and how far apart the dates are.", sql=_c_split()),
    Dataset("q2_key_e_identity", "extract", "Key E (site, type, no, creator, entry date): identities and repeated line keys.", sql=_e_identity()),
    Dataset("q3_line_repeats", "extract", "Repeated (seq, ledger, sub-ledger) line keys under key E: exact copies or distinct amounts.", sql=_line_repeats()),
)
packages.PACKAGES["entry_identity_probe_02"] = ENTRY_IDENTITY_PROBE_02
