"""Ageing bucket maths ONLY. Edges per the CFO brief (0-30, 31-60, 61-90, 91-180, 181-365, >365).
This module is deliberately basis-agnostic: WHICH date feeds it (invoice/document date, due date,
credit terms, other ERP date) is UNDECIDED pending live discovery of CUBE$FINOTSD. It contains no
creditor or advance classification logic and must not gain any until live evidence defines it."""
from datetime import date
from decimal import Decimal

BUCKETS = ("0-30", "31-60", "61-90", "91-180", "181-365", ">365")


def bucket_for(days: int) -> str:
    if days < 0:
        return "not-due"
    for edge, name in ((30, BUCKETS[0]), (60, BUCKETS[1]), (90, BUCKETS[2]), (180, BUCKETS[3]), (365, BUCKETS[4])):
        if days <= edge:
            return name
    return BUCKETS[5]


def age_days(basis_date: date, as_of: date) -> int:
    return (as_of - basis_date).days


def summarise(items: list[tuple[date, Decimal]], as_of: date) -> dict[str, Decimal]:
    out = {b: Decimal(0) for b in (*BUCKETS, "not-due")}
    for d, amt in items:
        out[bucket_for(age_days(d, as_of))] += amt
    return out
