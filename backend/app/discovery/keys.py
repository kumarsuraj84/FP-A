"""Source-row-key candidates from Oracle METADATA ONLY (never scans transaction rows).

Reads ALL_OBJECTS / ALL_TAB_COLUMNS / ALL_CONSTRAINTS / ALL_CONS_COLUMNS / ALL_INDEXES / ALL_IND_COLUMNS.
Output is evidence for a human decision - NOT a declaration of the final source_row_key.
Visibility depends on the account's privileges: an empty result can mean "no key" or "not visible"."""
from collections import defaultdict

STRONG, WEAK, NONE = "STRONG_CANDIDATE", "WEAK_CANDIDATE", "NO_METADATA_KEY"


def discover_keys(ora, owner: str, name: str, *, discriminator_column: str | None = None) -> dict:
    obj = ora.query("SELECT object_type FROM all_objects WHERE owner = :o AND object_name = :n", {"o": owner, "n": name})
    if not obj:
        raise LookupError(f"{owner}.{name} not visible in ALL_OBJECTS")
    cols = ora.query("SELECT column_name, nullable FROM all_tab_columns WHERE owner = :o AND table_name = :t ORDER BY column_id",
                     {"o": owner, "t": name})
    nullable = {c["COLUMN_NAME"]: c["NULLABLE"] == "Y" for c in cols}
    cons = ora.query(
        "SELECT c.constraint_name AS cname, c.constraint_type AS ctype, c.status AS cstatus, c.validated AS cvalidated, "
        "cc.column_name AS col, cc.position AS pos "
        "FROM all_constraints c JOIN all_cons_columns cc ON cc.owner = c.owner AND cc.constraint_name = c.constraint_name "
        "WHERE c.owner = :o AND c.table_name = :t AND c.constraint_type IN ('P', 'U') "
        "ORDER BY c.constraint_name, cc.position", {"o": owner, "t": name})
    idx = ora.query(
        "SELECT i.index_name AS iname, i.uniqueness AS uniq, i.status AS istatus, ic.column_name AS col, "
        "ic.column_position AS pos "
        "FROM all_indexes i JOIN all_ind_columns ic ON ic.index_owner = i.owner AND ic.index_name = i.index_name "
        "WHERE i.table_owner = :o AND i.table_name = :t ORDER BY i.index_name, ic.column_position", {"o": owner, "t": name})

    raw = []   # (kind, name, [cols], healthy, health_note)
    by = defaultdict(list)
    meta = {}
    for r in cons:
        by[r["CNAME"]].append((r["POS"], r["COL"])); meta[r["CNAME"]] = r
    for n_, cs in by.items():
        m = meta[n_]
        ok = m["CSTATUS"] == "ENABLED" and m["CVALIDATED"] == "VALIDATED"
        raw.append(("PRIMARY_KEY" if m["CTYPE"] == "P" else "UNIQUE_CONSTRAINT", n_, [c for _, c in sorted(cs)], ok,
                    None if ok else f"constraint {m['CSTATUS']}/{m['CVALIDATED']}"))
    ib, im, other = defaultdict(list), {}, []
    for r in idx:
        ib[r["INAME"]].append((r["POS"], r["COL"])); im[r["INAME"]] = r
    for n_, cs in ib.items():
        m = im[n_]; cl = [c for _, c in sorted(cs)]
        if m["UNIQ"] == "UNIQUE":
            ok = m["ISTATUS"] in ("VALID", "N/A")
            raw.append(("UNIQUE_INDEX", n_, cl, ok, None if ok else f"index status {m['ISTATUS']}"))
        else:
            other.append({"index": n_, "columns": cl})

    merged: dict[tuple, dict] = {}
    for kind, n_, cl, ok, note in raw:
        key = tuple(cl)
        c = merged.setdefault(key, {"columns": cl, "sources": [], "healthy": True, "notes": []})
        c["sources"].append({"kind": kind, "name": n_})
        c["healthy"] &= ok
        if note: c["notes"].append(note)
    cands = []
    for c in merged.values():
        nulls = [x for x in c["columns"] if nullable.get(x, True)]
        expr = [x for x in c["columns"] if x.startswith("SYS_NC")]
        reasons = list(c["notes"])
        if nulls: reasons.append(f"nullable columns: {nulls}")
        if expr: reasons.append("contains function-based/expression column")
        if not c["healthy"] and not c["notes"]: reasons.append("not enabled/valid")
        rec = STRONG if (not nulls and not expr and c["healthy"]) else WEAK
        cands.append({"columns": c["columns"], "sources": c["sources"], "nullable_columns": nulls,
                      "includes_discriminator": (discriminator_column in c["columns"]) if discriminator_column else None,
                      "recommendation": rec, "reasons": reasons})
    cands.sort(key=lambda c: (c["recommendation"] != STRONG, any(s["kind"] != "PRIMARY_KEY" for s in c["sources"]), len(c["columns"])))
    overall = STRONG if any(c["recommendation"] == STRONG for c in cands) else (WEAK if cands else NONE)
    note = "Evidence only - NOT a final source_row_key; requires live review."
    if obj[0]["OBJECT_TYPE"] in ("VIEW",):
        note += " Object is a VIEW: constraints/indexes belong to underlying tables and are not inferred here."
    if discriminator_column:
        note += f" Shared object: keys apply to the shared table; source identity also carries {discriminator_column}."
    if overall == NONE:
        note += " No P/U constraint or unique index visible to this account (may be a visibility limit)."
    return {"object": f"{owner}.{name}", "object_type": obj[0]["OBJECT_TYPE"], "recommendation": overall,
            "candidates": cands, "other_non_unique_indexes": other, "note": note}
