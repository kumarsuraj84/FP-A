<!-- Read from the mart itself by the loader login (cred_loader_login) after the first real load. Aggregates only: no vendor names or codes. -->
# Mart load report: run_20261004_006

as_of_date 2026-10-04; loaded by `cred_loader_login` in 0.0s
**State: recon_state `verified`, publication_state `unpublished`** (live runs: 0)

## Rows
- open_item: 12,233
- vendor_snapshot: 2,018
- distinct_source_keys: 12,233
- identity_snapshot: 110,092
- distinct vendors: 2,018

## Amounts (₹ Cr)
- Credit outstanding 404.38
- Creditor debit balance (classification pending) 111.71
- Signed net -292.67

## Controls
- 561 recorded, 561 PASS (source to extract 414, extract to mart 147)
- maximum absolute variance: 0.0000; extract vs mart row variance 0.0000; monetary variance 0.0000
- structural checks M1-M10 (violations): {"M8_identity_vs_items": 0, "M1_rows_vs_expected": 0, "M6_item_without_vendor": 0, "M2_duplicate_business_key": 0, "M7_sign_or_open_violation": 0, "M9_as_of_mismatch": 0, "M10_derived_inconsistent": 0, "M5_duplicate_k1_signature": 0, "M4_key_not_rederivable": 0, "M3_key_conflicting_identity": 0}

## Ledger totals
| Ledger | Dr/Cr | Rows | ₹ Cr abs | ₹ Cr signed |
|---|---|---|---|---|
| 1000000024 | Cr | 3,843 | 116.94 | -116.94 |
| 1000000024 | Dr | 2,674 | 84.75 | 84.75 |
| 1000000025 | Cr | 308 | 6.45 | -6.45 |
| 1000000025 | Dr | 172 | 4.06 | 4.06 |
| 1000000026 | Cr | 3,585 | 229.13 | -229.13 |
| 1000000026 | Dr | 348 | 17.65 | 17.65 |
| 1000000092 | Cr | 1,246 | 51.85 | -51.85 |
| 1000000092 | Dr | 57 | 5.25 | 5.25 |

## Document Age
| Bucket | Dr/Cr | Rows | ₹ Cr abs |
|---|---|---|---|
| D0_30 | Cr | 2,373 | 122.89 |
| D0_30 | Dr | 667 | 26.91 |
| D181_365 | Cr | 537 | 38.84 |
| D181_365 | Dr | 340 | 20.82 |
| D31_60 | Cr | 2,445 | 118.13 |
| D31_60 | Dr | 699 | 19.30 |
| D365_PLUS | Cr | 791 | 13.29 |
| D365_PLUS | Dr | 422 | 8.93 |
| D61_90 | Cr | 1,738 | 84.93 |
| D61_90 | Dr | 613 | 15.63 |
| D91_180 | Cr | 1,098 | 26.30 |
| D91_180 | Dr | 509 | 20.11 |
| UNCLASSIFIED_AFTER_AS_OF | Dr | 1 | 0.00 |

## Due Status
| Status | Dr/Cr | Rows | ₹ Cr abs |
|---|---|---|---|
| DUE_UNAVAILABLE | Cr | 1,027 | 37.87 |
| DUE_UNAVAILABLE | Dr | 3,187 | 108.90 |
| NOT_YET_DUE | Cr | 1,868 | 99.29 |
| NOT_YET_DUE | Dr | 4 | 0.13 |
| PAST_DUE_OR_DUE_TODAY | Cr | 6,087 | 267.21 |
| PAST_DUE_OR_DUE_TODAY | Dr | 60 | 2.68 |

