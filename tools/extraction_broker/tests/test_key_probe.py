import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import guard  # noqa: E402
from packages import CREDITOR_LEDGERS, KEY_CANDIDATES, KEY_COMPONENTS, PACKAGES, PAYABLES_PROBE_03  # noqa: E402

MUTABLE = ("pending", "adjusted", "narration")


def test_registered_and_every_dataset_passes_the_guard():
    assert "payables_probe_03" in PACKAGES
    assert [d.name for d in PAYABLES_PROBE_03] == ["s1_key_uniqueness", "s2_key_component_nulls", "s3_duplicate_structure"]
    for d in PAYABLES_PROBE_03:
        assert guard.check(d.sql, d.kind).kind == "extract", d.name


def test_candidates_are_the_agreed_hierarchy_built_one_field_at_a_time():
    k = KEY_CANDIDATES
    assert k["K1"] == ("document_code", "ledger_code", "sub_ledger_code", "drcr")
    assert k["K2"] == k["K1"] + ("ref_no",)
    assert k["K3"] == k["K2"] + ("document_date",)
    assert k["K4"] == k["K3"] + ("amount",)
    assert k["K2A"] == k["K2"] + ("amount",)  # amount without the date, to see which field resolves ties
    assert set(k["K4"]) < set(k["K5"])


def test_no_candidate_key_uses_mutable_accounting_state_or_free_text():
    for name, cols in KEY_CANDIDATES.items():
        for c in cols:
            assert c not in MUTABLE, (name, c)
    for d in PAYABLES_PROBE_03:
        # PENDING appears only in the open-row scope predicate, never inside a key expression
        for m in re.findall(r"GROUP BY ([^)]*?)(?: HAVING|\))", d.sql):
            assert not any(x in m.lower() for x in MUTABLE), (d.name, m)
    for c in KEY_COMPONENTS:
        assert c not in MUTABLE


def test_scope_is_the_four_creditor_ledgers_only_in_both_open_and_all_variants():
    for d in PAYABLES_PROBE_03:
        sql = d.sql
        assert sql.count("o.ledger_code IN (1000000026, 1000000024, 1000000092, 1000000025)") >= 2, d.name
        for excluded in ("1000000029", "1000000014", "1114925452"):  # TDS Payable, Sundry Debtors, Inter-Company
            assert excluded not in sql, (d.name, excluded)
        assert "o.pending <> 0" in sql  # the open variant
        assert "'open' AS scope_name" in sql and "'all' AS scope_name" in sql


def test_misretail_only_aggregates_and_nothing_row_level_leaves_oracle():
    for d in PAYABLES_PROBE_03:
        up = d.sql.upper()
        assert "SSRK" not in up and "PUBLIC" not in up and "T$FINOTSD_637" not in up, d.name
        for obj in re.findall(r"(?i)\b(?:from)\s+([\w$#\".]+)", d.sql):
            assert obj.upper().startswith("MISRETAIL.") or obj == "(", (d.name, obj)
        assert "REPORT_DATE >= DATE" in up
        outer = re.match(r"(?is)select scope_name, [a-z_, ]+ from \(", d.sql)
        assert outer, d.name  # the outermost select is over inline aggregate views only
        for alias in re.findall(r"(?i)\bAS\s+([a-z_][a-z0-9_$#]*)", d.sql):
            assert len(alias) <= 30, (d.name, alias)
    # the only string literals are fixed labels, never data values
    for d in PAYABLES_PROBE_03:
        lits = set(re.findall(r"'([^']*)'", d.sql))
        allowed = {"open", "all", "~", "|"} | set(KEY_CANDIDATES) | {"doc_code_many_rows", "doc_code_sub_ledger_many_rows", "doc_code_ledger_both_drcr", "doc_code_many_sub_ledgers"}
        assert lits <= allowed | {"2026-01-01"}, (d.name, lits - allowed)


def test_duplicate_counts_cover_what_was_asked():
    s1 = PAYABLES_PROBE_03[0].sql
    for piece in ("total_rows", "distinct_keys", "surplus_rows", "rows_in_dup_groups", "dup_groups", "max_group_size"):
        assert piece in s1
    s2 = PAYABLES_PROBE_03[1].sql
    for c in KEY_COMPONENTS:
        assert f"AS n_{c}" in s2
    s3 = PAYABLES_PROBE_03[2].sql
    for pat in ("doc_code_many_rows", "doc_code_sub_ledger_many_rows", "doc_code_ledger_both_drcr"):
        assert pat in s3
    assert CREDITOR_LEDGERS == (1000000026, 1000000024, 1000000092, 1000000025)
