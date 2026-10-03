# Known gaps
> **NO LIVE FINANCIAL DATA HAS YET BEEN VALIDATED.**

## Blockers
- BLOCKED: read-only Oracle account + network route from the execution environment to the MIS Oracle host.
- BLOCKED: PostgreSQL target not provisioned (DDL untested on a live server).

## To be answered by the database (NOT for Finance)
Cube→physical resolution and refresh state; why/whether copy ids are non-sequential (irrelevant — ids need not be chronological); SITE_REG structure, release statuses and coverage; whether an all-years SITE_REG copy exists and overlaps yearly copies; existing P&L view definitions; creditor/subledger structure in FINSL/FINGL/FINOTSD; whether FINOTSD carries invoice date, due date, adjustment links; debit-balance creditor patterns and what vendor advances look like; cash/bank GL candidates and opening-balance logic.

## Deferred Finance questions (to be drafted AFTER live discovery; expected to be few)
Populated only with residue the data cannot settle, e.g. policy choices (ageing basis when both dates exist, overdue policy/credit terms if not in data, treatment of ambiguous debit balances, BS grouping sign-off). None are asked now.

## Technical gaps
Canonical transaction key unknown; ingestion jobs themselves (extract→stage→promote against real schemas) not written; auth/RBAC and config-audit triggers not implemented; no reconciliation evidence exists.

## Added in patch 2
MACHINE_VERIFIED relies on a generic cell-value match until OLAP_DATACUBE_LIST's real columns are known; expect most early confirmations to be OPERATOR_CONFIRMED and tighten the matcher after the first live read. Which cubes are shared vs separate-object is unknown.
