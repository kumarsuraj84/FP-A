"""Source Fix Candidate queue: recurring corrections and recurring mapping changes, ranked for the extraction / data team. ADVISORY ONLY: the queue never changes a mapping, a
correction or finance data. The data team records a source fix; the platform then checks whether the pattern really stopped (post-fix validation). Originating correction and
mapping ids are kept on every candidate.

Rank = 100 x cube root of (recurrence x materiality x breadth), each 0..1: recurrence = distinct months (cap 6) / 6; materiality = cumulative moved amount (cap 5 Cr) / 5;
breadth = (lines + sites) (cap 20) / 20. For a recurring mapping change recurrence = changes (cap 4) / 4 and materiality is neutral (0.5). Thresholds are UNCALIBRATED and versioned."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date
from decimal import Decimal

import psycopg

from ..adjustments.service import Problem, db_error
from ..auth.service import Actor, audit

D = Decimal
CR = D(10_000_000)
THRESHOLD_VERSION = "2026-10-uncalibrated-1"
THRESHOLDS = {"min_lines": 5, "min_months_with_lines": [3, 3], "min_cumulative_cr_with_lines": [1.0, 2], "mapping_min_versions": 3}
WORKERS = ("fpa_manager", "finance_reviewer", "controller", "admin")
APPROVED_STATUSES = ("ACTIVE", "REVERSAL_REQUESTED", "SUPERSEDED_BY_SOURCE", "SOURCE_REVIEW_REQUIRED")


def need(actor: Actor, what: str) -> None:
    if actor.role not in WORKERS:
        raise Problem(f"Your role ({actor.role}) cannot {what}.", 403)


def month_index(d: date) -> int:
    return d.year * 12 + d.month


def from_index(i: int) -> date:
    return date((i - 1) // 12, (i - 1) % 12 + 1, 1)


def longest_run(months: set[int]) -> int:
    best = run = 0
    prev = None
    for m in sorted(months):
        run = run + 1 if prev is not None and m == prev + 1 else 1
        best, prev = max(best, run), m
    return best


def score_of(rec: float, mat: float, breadth: float) -> D:
    return D(str(round(100 * (max(rec, 0) * max(mat, 0) * max(breadth, 0)) ** (1 / 3), 2)))


def qualifies(lines: int, months: int, cum_cr: D) -> bool:
    t = THRESHOLDS
    return lines >= t["min_lines"] or (months >= t["min_months_with_lines"][0] and lines >= t["min_months_with_lines"][1]) or (abs(cum_cr) >= D(str(t["min_cumulative_cr_with_lines"][0])) and lines >= t["min_cumulative_cr_with_lines"][1])


def pattern_key(issue: str, entity, subject: str, a, b) -> str:
    return hashlib.sha256("|".join(str(x).strip().upper() for x in (issue, entity or "", subject, a or "", b or "")).encode()).hexdigest()


def derive(corr_rows: list[dict], map_rows: list[dict], names: dict | None = None) -> list[dict]:
    """Pure. corr_rows: approved correction lines (source_entity, ledger_key, original_group, corrected_group, original_month, corrected_month, source_amount_snapshot, site_code, request_id);
    map_rows: ACTIVE/RETIRED mapping rules (mapping_id, domain, source_key, mapped_value, version). -> candidate dicts."""
    names = names or {}
    groups: dict[tuple, list] = {}
    for r in corr_rows:
        if r["corrected_group"]:
            groups.setdefault(("RECURRING_GROUP_RECLASS", r["source_entity"], str(r["ledger_key"]), r["original_group"], r["corrected_group"]), []).append(r)
        if r["corrected_month"]:
            shift = month_index(r["corrected_month"]) - month_index(r["original_month"])
            groups.setdefault(("RECURRING_MONTH_SHIFT", r["source_entity"], str(r["ledger_key"]), "0", f"{shift:+d}"), []).append(r)
    out = []
    for (issue, ent, subj, a, b), rows in groups.items():
        months = {month_index(r["original_month"]) for r in rows}
        cum = sum((abs(D(r["source_amount_snapshot"])) for r in rows), D(0)) / CR
        sites = {r["site_code"] for r in rows if r["site_code"]}
        reqs = sorted({str(r["request_id"]) for r in rows})
        if not qualifies(len(rows), len(months), cum):
            continue
        name = names.get((ent, subj), subj)
        fix = (f"Fix the upstream ledger-to-management-group mapping so ledger {name} posts to {b} instead of {a}." if issue == "RECURRING_GROUP_RECLASS"
               else f"Capture the expense month at source for ledger {name}: the booked month differs from the service month by {b} month(s).")
        out.append({"pattern_key": pattern_key(issue, ent, subj, a, b), "issue_type": issue, "entity": ent, "subject_key": subj, "subject_name": name, "from_value": a if issue == "RECURRING_GROUP_RECLASS" else None,
                    "to_value": b if issue == "RECURRING_GROUP_RECLASS" else b, "correction_count": len(reqs), "line_count": len(rows), "site_count": len(sites), "months_affected": len(months),
                    "consecutive_months": longest_run(months), "cumulative_amount_cr": cum.quantize(D("0.0001")), "first_seen": from_index(min(months)), "last_seen": from_index(max(months)), "recommended_fix": fix, "origin_ids": reqs,
                    "score": score_of(min(len(months), 6) / 6, min(float(cum) / 5, 1), min((len(rows) + len(sites)) / 20, 1))})
    by_key: dict[tuple, list] = {}
    for r in map_rows:
        by_key.setdefault((r["domain"], r["source_key"]), []).append(r)
    for (domain, key), rows in by_key.items():
        if len(rows) >= THRESHOLDS["mapping_min_versions"]:
            changes = len(rows) - 1
            out.append({"pattern_key": pattern_key("RECURRING_MAPPING_CHANGE", None, f"{domain}:{key}", None, None), "issue_type": "RECURRING_MAPPING_CHANGE", "entity": None, "subject_key": f"{domain}:{key}",
                        "subject_name": key, "from_value": None, "to_value": rows[-1]["mapped_value"], "correction_count": 0, "line_count": 0, "site_count": 0, "months_affected": changes, "consecutive_months": 0,
                        "cumulative_amount_cr": D(0), "first_seen": None, "last_seen": None, "origin_ids": [str(r["mapping_id"]) for r in rows],
                        "recommended_fix": f"The mapping of {key} has been changed {changes} times: agree the permanent rule with Finance and fix the classification at source.",
                        "score": score_of(min(changes, 4) / 4, 0.5, 0.5)})
    return sorted(out, key=lambda c: -c["score"])


def view(r: dict) -> dict:
    out = {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in r.items()}
    out["advisory"] = "Advisory only: this queue never changes a mapping, a correction or finance data."
    return out


def add_event(conn, actor: Actor | None, cid: str, etype: str, to: str, comment=None, fix_date=None) -> None:
    try:
        conn.execute("INSERT INTO source_fix_event (candidate_id, event_type, to_status, actor_user_id, actor_label, comment, fix_date) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                     (cid, etype, to, actor.user_id if actor else None, None if actor else "system", comment, fix_date))
    except psycopg.Error as e:
        conn.rollback()
        raise db_error(e) from None
    audit(conn, actor.email if actor else "system", "sourcefix_" + etype.lower(), "source_fix_candidate", str(cid), {"to_status": to, "comment": comment}, actor.user_id if actor else None)


def fetch(conn, cid: str) -> dict:
    r = conn.execute("SELECT * FROM source_fix_candidate WHERE candidate_id = %s", (cid,)).fetchone()
    if r is None:
        raise Problem("No such candidate.", 404)
    return r


def ledger_names(gold, rows: list[dict]) -> dict:
    if gold is None or not rows:
        return {}
    out = {}
    try:
        with gold.session("pnl") as g:
            for ent in {r["source_entity"] for r in rows}:
                codes = sorted({int(r["ledger_key"]) for r in rows if r["source_entity"] == ent and str(r["ledger_key"]).isdigit()})
                for x in g.execute("SELECT DISTINCT glcode, glname FROM gold_fpa.voucher_lines WHERE entity = %s AND glcode = ANY(%s)", (ent, codes)).fetchall():
                    out[(ent, str(x["glcode"]))] = x["glname"]
    except Exception:  # noqa: BLE001  names are a convenience; the code is kept
        return out
    return out


def refresh(conn, gold, actor: Actor) -> dict:
    """Recompute the candidates from the corrections and mapping versions, update the live ones, raise new ones, and run the post-fix validation of implemented fixes."""
    need(actor, "refresh the source fix queue")
    corr = conn.execute("""SELECT r.source_entity, l.ledger_key, l.original_group, l.corrected_group, l.original_month, l.corrected_month, l.source_amount_snapshot, l.site_code, r.request_id
                           FROM correction_line l JOIN correction_request r USING (request_id) WHERE r.status = ANY(%s)""", (list(APPROVED_STATUSES),)).fetchall()
    maps = conn.execute("SELECT mapping_id, domain, source_key, mapped_value, version FROM mapping_rule WHERE status IN ('ACTIVE', 'RETIRED') AND source = 'app' ORDER BY domain, source_key, version").fetchall()
    cands = derive(corr, maps, ledger_names(gold, corr))
    out = {"raised": 0, "updated": 0, "validated": 0, "still_recurring": 0, "candidates": len(cands)}
    for c in cands:
        live = conn.execute("SELECT candidate_id FROM source_fix_candidate WHERE pattern_key = %s AND status NOT IN ('VALIDATED', 'DISMISSED')", (c["pattern_key"],)).fetchone()
        cols = ("subject_name", "correction_count", "line_count", "site_count", "months_affected", "consecutive_months", "cumulative_amount_cr", "first_seen", "last_seen", "score", "recommended_fix")
        if live:
            conn.execute(f"UPDATE source_fix_candidate SET {', '.join(f'{k} = %s' for k in cols)}, origin_ids = %s::jsonb, threshold_version = %s, updated_at = now() WHERE candidate_id = %s",
                         [c[k] for k in cols] + [json.dumps(c["origin_ids"]), THRESHOLD_VERSION, live["candidate_id"]])
            out["updated"] += 1
            continue
        row = conn.execute("""INSERT INTO source_fix_candidate (pattern_key, issue_type, entity, subject_key, subject_name, from_value, to_value, correction_count, line_count, site_count, months_affected,
                                  consecutive_months, cumulative_amount_cr, first_seen, last_seen, score, recommended_fix, origin_ids, threshold_version)
                              VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s) RETURNING candidate_id""",
                           (c["pattern_key"], c["issue_type"], c["entity"], c["subject_key"], c["subject_name"], c["from_value"], c["to_value"], c["correction_count"], c["line_count"], c["site_count"], c["months_affected"],
                            c["consecutive_months"], c["cumulative_amount_cr"], c["first_seen"], c["last_seen"], c["score"], c["recommended_fix"], json.dumps(c["origin_ids"]), THRESHOLD_VERSION)).fetchone()
        add_event(conn, None, str(row["candidate_id"]), "DETECTED", "OPEN")
        out["raised"] += 1
    v = validate_fixes(conn)
    out.update(validated=v["validated"], still_recurring=v["still_recurring"])
    conn.commit()
    return out


def validate_fixes(conn) -> dict:
    """For each FIX_IMPLEMENTED candidate: did the pattern come back after the fix date? New approved correction lines of the same pattern on a posting month from the fix month on mean it did
    (STILL_RECURRING); none after one full complete month since the fix means the fix worked (VALIDATED); otherwise it is still pending."""
    out = {"validated": 0, "still_recurring": 0, "pending": 0}
    today = date.today()
    for c in conn.execute("SELECT * FROM source_fix_candidate WHERE status = 'FIX_IMPLEMENTED'").fetchall():
        fix = c["source_fix_date"]
        if c["issue_type"] == "RECURRING_MAPPING_CHANGE":
            domain, _, key = c["subject_key"].partition(":")
            n = conn.execute("SELECT count(*) AS n FROM mapping_rule WHERE domain = %s AND source_key = %s AND status IN ('ACTIVE', 'RETIRED') AND source = 'app' AND created_at::date > %s", (domain, key, fix)).fetchone()["n"]
        else:
            col = "corrected_group = %s AND original_group = %s" if c["issue_type"] == "RECURRING_GROUP_RECLASS" else "corrected_month IS NOT NULL"
            args = [c["entity"], c["subject_key"], fix.replace(day=1), fix]
            extra = []
            if c["issue_type"] == "RECURRING_GROUP_RECLASS":
                extra = [c["to_value"], c["from_value"]]
            n = conn.execute(f"""SELECT count(*) AS n FROM correction_line l JOIN correction_request r USING (request_id) WHERE r.source_entity = %s AND l.ledger_key = %s AND l.original_month >= %s
                                 AND r.requested_at::date > %s AND r.status = ANY(%s) AND {col}""", args + [list(APPROVED_STATUSES)] + extra).fetchone()["n"]
        full_month_passed = month_index(today) - month_index(fix) >= 2
        if n > 0:
            add_event(conn, None, str(c["candidate_id"]), "VALIDATION_FAILED", "STILL_RECURRING", f"{n} new correction line(s) of this pattern since the source fix.")
            out["still_recurring"] += 1
        elif full_month_passed:
            add_event(conn, None, str(c["candidate_id"]), "VALIDATED", "VALIDATED", "No correction of this pattern since the source fix, over a complete month.")
            out["validated"] += 1
        else:
            out["pending"] += 1
    return out


ACTIONS = {"acknowledge": ("ACKNOWLEDGED", "ACKNOWLEDGED"), "dismiss": ("DISMISSED", "DISMISSED")}


def act(conn, actor: Actor, cid: str, action: str, comment: str | None = None, fix_date: str | None = None) -> dict:
    need(actor, "act on the source fix queue")
    fetch(conn, cid)
    if action == "implemented":
        try:
            d = date.fromisoformat(str(fix_date))
        except ValueError:
            raise Problem("Give the date of the source fix, like 2026-10-20.") from None
        if d > date.today():
            raise Problem("The source fix date cannot be in the future.")
        add_event(conn, actor, cid, "FIX_IMPLEMENTED", "FIX_IMPLEMENTED", comment, d)
    elif action in ACTIONS:
        et, to = ACTIONS[action]
        if action == "dismiss" and len((comment or "").strip()) < 10:
            raise Problem("Give a reason of at least 10 characters.")
        add_event(conn, actor, cid, et, to, comment)
    elif action == "comment":
        if len((comment or "").strip()) < 3:
            raise Problem("Write a comment.")
        c = fetch(conn, cid)
        add_event(conn, actor, cid, "COMMENTED", c["status"], comment.strip())
    else:
        raise Problem("Unknown action.", 404)
    conn.commit()
    return view(fetch(conn, cid))


def set_owners(conn, actor: Actor, cid: str, finance_owner: str | None, data_owner: str | None) -> dict:
    need(actor, "assign owners")
    fetch(conn, cid)
    conn.execute("UPDATE source_fix_candidate SET finance_owner = %s, data_owner = %s, updated_at = now() WHERE candidate_id = %s", ((finance_owner or "").strip() or None, (data_owner or "").strip() or None, cid))
    audit(conn, actor.email, "sourcefix_owners_set", "source_fix_candidate", cid, {"finance_owner": finance_owner, "data_owner": data_owner}, actor.user_id)
    conn.commit()
    return view(fetch(conn, cid))


def listing(conn, status: str | None, issue: str | None, limit: int, offset: int) -> dict:
    where, args = [], []
    where.append("status = %s" if status else "status NOT IN ('VALIDATED', 'DISMISSED')")
    if status:
        args.append(status.upper())
    if issue:
        where.append("issue_type = %s")
        args.append(issue.upper())
    w = "WHERE " + " AND ".join(where)
    total = conn.execute(f"SELECT count(*) AS n FROM source_fix_candidate {w}", args).fetchone()["n"]
    rows = conn.execute(f"SELECT * FROM source_fix_candidate {w} ORDER BY score DESC, last_seen DESC NULLS LAST LIMIT %s OFFSET %s", args + [limit, offset]).fetchall()
    counts = {r["status"]: r["n"] for r in conn.execute("SELECT status, count(*) AS n FROM source_fix_candidate GROUP BY status").fetchall()}
    return {"total": total, "counts": counts, "items": [view(r) for r in rows], "threshold_version": THRESHOLD_VERSION, "calibration_status": "UNCALIBRATED", "thresholds": THRESHOLDS,
            "advisory": "Advisory only: this queue never changes a mapping, a correction or finance data."}


def history(conn, cid: str) -> list[dict]:
    fetch(conn, cid)
    return [dict(r) for r in conn.execute("""SELECT e.seq, e.event_type, e.from_status, e.to_status, e.comment, e.fix_date, e.at, coalesce(u.email, e.actor_label) AS actor
                                             FROM source_fix_event e LEFT JOIN app_user u ON u.user_id = e.actor_user_id WHERE e.candidate_id = %s ORDER BY e.seq""", (cid,)).fetchall()]


def export_text(conn) -> str:
    """A plain list for the extraction team: one block per open candidate, ranked."""
    rows = conn.execute("SELECT * FROM source_fix_candidate WHERE status IN ('OPEN', 'ACKNOWLEDGED', 'STILL_RECURRING') ORDER BY score DESC").fetchall()
    lines = [f"Source fix candidates (advisory, {THRESHOLD_VERSION}, uncalibrated)", ""]
    for i, r in enumerate(rows, 1):
        lines += [f"{i}. [{r['issue_type']}] {r['subject_name'] or r['subject_key']} ({r['entity'] or 'n/a'}), score {r['score']}", f"   {r['recommended_fix']}",
                  f"   {r['correction_count']} corrections, {r['line_count']} lines, {r['site_count']} sites, {r['months_affected']} months, {r['cumulative_amount_cr']} Cr moved, last seen {r['last_seen'] or 'n/a'}", ""]
    return "\n".join(lines)
