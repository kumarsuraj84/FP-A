"""Creditors API: read-only serving of one verified mart run (candidate preview first, live after promotion).

Masking is enforced by the DATABASE, not by this code: every request runs under SET LOCAL ROLE into exactly one of cred_verifier,
cred_api_reader or cred_finance_reader, and only the finance role can read vendor names, vendor codes or document identifiers.
"""
