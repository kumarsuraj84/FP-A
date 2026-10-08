"""
FP&A-side SQL guard for the extraction broker.

Why this exists: the Inventory Automation app validates SQL only when a query is *saved* through its API, its
extraction engine does not re-check at run time, and its keyword list is shorter than ours. The Oracle login it
uses is broad, so every statement is checked here BEFORE it is registered, and the check is stricter on purpose:

  safety       single SELECT/WITH only; no DML, DDL, PL/SQL, locking, packages, db-links, INTO
  scope        any schema the read-only Oracle login can read (scope lifted on 2026-10-07 at the user's instruction:
               MISRETAIL and SSRK). Every data object must still be OWNER-qualified (no PUBLIC synonym can silently
               resolve elsewhere). Oracle's own internal schemas and the DBA_ / V$ / X$ dictionary stay blocked.
               SSRK is live production: the row cap, date bound and one-query-at-a-time rules matter most there.
  performance  every query declares a kind and must END with a hard row cap; data queries must also be bounded
               (a date predicate) so nothing can become an all-history scan
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

_COMMENTS = re.compile(r"--[^\n]*|/\*.*?\*/", re.S)
_LITERALS = re.compile(r"'(?:[^']|'')*'")

# Includes everything the Inventory app blocks, plus PL/SQL, locking, packages and data-moving constructs.
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|merge|drop|alter|create|truncate|grant|revoke|rename|comment|"
    r"execute|exec|call|begin|declare|commit|rollback|savepoint|lock|flashback|purge|analyze|"
    r"explain|into|dbms_\w+|utl_\w+|sys_context|sp_\w*|xp_\w*)\b",
    re.I,
)
_FOR_UPDATE = re.compile(r"\bfor\s+update\b", re.I)
_DB_LINK = re.compile(r"@\s*\w")
# Personal / contact data is never extracted: this pipeline needs codes, names, terms and amounts, not people's details.
_PII = re.compile(
    r"\b(\w*addr\w*|\w*phone\w*|ph\d|\w*email\w*|\w*mobile\w*|pan_no|\w*contact\w*|\w*fax\w*|\w*billing_\w+|pin|\w*gstin\w*|\w*customername\w*)\b",
    re.I,
)
# Exact payment-mode column names that merely contain a flagged word ("PhonePe" is a tender type, not a phone number). Exact names only, never a pattern.
_PII_ALLOWED = re.compile(r"(?<![\w])mop_phonepe(?![\w])", re.I)
_STARTS = re.compile(r"(?is)^\s*(select|with)\b")
_TRAILING_CAP = re.compile(r"\bfetch\s+first\s+(\d+)\s+rows?\s+only\s*$", re.I)
# Still blocked, whatever the login can read: Oracle's own internal schemas (credentials, internals, no finance value),
# the DBA / dynamic-performance dictionary, and PUBLIC-qualified names.
_OUT_OF_SCOPE = re.compile(
    r"\b(sys|system|dbsnmp|xdb|mdsys|ctxsys|scott|outln|wmsys|exfsys|dvsys|lbacsys|audsys|ordsys|olapsys|appqossys|"
    r"dba_\w+|v\$\w+|gv\$\w+|x\$\w+)\b|\bpublic\s*\.",
    re.I,
)
# Privilege-introspection views a metadata query may read besides ALL_* / USER_*: they show only the login's own grants.
_SELF_VIEWS = ("SESSION_PRIVS", "SESSION_ROLES", "ROLE_SYS_PRIVS", "ROLE_TAB_PRIVS", "ROLE_ROLE_PRIVS")
_DICTIONARY = re.compile(r"\bfrom\s+(all|user)_\w+", re.I)
_FROM_OBJECTS = re.compile(r"\b(?:from|join)\s+([\w$#\".]+)", re.I)
_DATE_BOUND = re.compile(r"(>=|<=|>|<|between)\s*(date\s*'|to_date\s*\(|:\w+|sysdate)", re.I)

# Hard ceilings per kind: the broker refuses anything above these, whatever the package asks for.
# master = small reference tables (ledger / sub-ledger masters): named columns only, no date bound needed
MAX_ROWS = {"metadata": 300_000, "sample": 1_000, "master": 100_000, "extract": 5_000_000}


class GuardError(ValueError):
    """The statement is not allowed. The message says why, in plain words."""


@dataclass(frozen=True)
class Checked:
    sql: str
    kind: str
    row_cap: int
    query_hash: str


def normalise(sql: str) -> str:
    return re.sub(r"\s+", " ", _COMMENTS.sub(" ", sql)).strip().rstrip(";").strip()


def query_hash(sql: str) -> str:
    return hashlib.sha256(normalise(sql).lower().encode("utf-8")).hexdigest()


def _row_cap(stripped: str) -> int | None:
    """The cap is the statement's OUTERMOST one: it must be the final clause. An inner FETCH FIRST (e.g. one row per
    table inside a UNION) bounds only that branch, so it can never stand in for a cap on the whole result."""
    m = _TRAILING_CAP.search(stripped)
    return int(m.group(1)) if m else None


def check(sql: str, kind: str) -> Checked:
    """Raise GuardError unless `sql` is a safe, capped, bounded read of the declared `kind`."""
    if kind not in MAX_ROWS:
        raise GuardError(f"unknown query kind '{kind}'")
    stripped = normalise(sql)
    if not stripped:
        raise GuardError("empty statement")
    if ";" in stripped:
        raise GuardError("multiple statements are not allowed")
    if not _STARTS.match(stripped):
        raise GuardError("only SELECT / WITH statements are allowed")
    no_lit = _LITERALS.sub("''", stripped)
    m = _FORBIDDEN.search(no_lit)
    if m:
        raise GuardError(f"forbidden keyword: {m.group(0)}")
    if _FOR_UPDATE.search(no_lit):
        raise GuardError("FOR UPDATE is not allowed")
    if _DB_LINK.search(no_lit):
        raise GuardError("database links are not allowed")

    oos = _OUT_OF_SCOPE.search(stripped)  # literals included: owner names live inside string literals
    if oos:
        raise GuardError(f"out of scope: '{oos.group(0)}' (Oracle internals, the DBA / V$ dictionary and PUBLIC names are never read)")

    cap = _row_cap(no_lit)
    if cap is None:
        raise GuardError("every query must END with a hard row cap (FETCH FIRST n ROWS ONLY)")
    if cap > MAX_ROWS[kind]:
        raise GuardError(f"row cap {cap:,} exceeds the {kind} ceiling of {MAX_ROWS[kind]:,}")

    objects = [o.strip('"').upper() for o in _FROM_OBJECTS.findall(no_lit)]
    dict_view = lambda o: o.split(".")[-1].startswith(("ALL_", "USER_")) or o.split(".")[-1] in _SELF_VIEWS  # noqa: E731
    dictionary_only = bool(objects) and all(dict_view(o) for o in objects)
    if kind == "metadata" and not dictionary_only:
        raise GuardError("a metadata query may only read ALL_* / USER_* dictionary views (or the login's own privilege views)")
    if kind != "metadata":
        ctes = {n.upper() for n in re.findall(r"(?:\bwith|,)\s*(\w+)\s+as\s*\(", no_lit, re.I)}      # names the statement defines itself are not database objects
        unscoped = [o for o in objects if "." not in o and o not in ctes]
        if unscoped:
            raise GuardError(f"data objects must be OWNER-qualified (found {unscoped[0]})")
    if kind != "metadata" and dictionary_only:
        raise GuardError("a data query must read data objects, not only dictionary views")
    if kind != "metadata":
        pii = _PII.search(_PII_ALLOWED.sub("", no_lit))
        if pii:
            raise GuardError(f"personal / contact data is not extracted (column '{pii.group(0)}')")
    if kind == "extract" and not _DATE_BOUND.search(no_lit):
        raise GuardError("an extract must be bounded by a date predicate (>=, <=, BETWEEN) so it cannot scan all history")
    if kind in ("extract", "master") and re.search(r"(?i)select\s+(distinct\s+)?\*", no_lit):
        raise GuardError(f"a{'n' if kind == 'extract' else ''} {kind} must name its columns (no SELECT *)")
    return Checked(sql=sql.strip().rstrip(";").strip(), kind=kind, row_cap=cap, query_hash=query_hash(sql))
