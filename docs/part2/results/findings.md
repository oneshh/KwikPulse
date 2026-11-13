# Part 2 | Can these numbers be trusted?

**Scope:** 2026-07-27 to 2026-10-25, Monday–Sunday **Asia/Kolkata** weeks.
**Input:** `orders.csv` (SHA-256 `45c370099f3c735898cdd199575c0ff7dd29de2dd9780cad0e397169bb8ace16`); Python standard library.
**Rate:** `100 * number_of_COD_orders_status_RTO / (number_COD_RTO + number_COD_delivered)`.

## Executive answer

- **97,378 raw rows**, **1,439 exact excess duplicates**, **95,939 unique usable orders**, **26 merchant IDs** (24 non-test and 2 named tests).
- All-time, all-merchant **30.20%** = 14,394 / 47,664 COD final outcomes.
- All-time, *non-test* **28.37%** = 13,108 / 46,211 COD final outcomes.
- **287 unique orders missing timestamps**, including **150 final-outcome COD**. These count for all-time merchant ranking but not weekly trends.
- **2 days with zero date-stamped orders**, 2026-09-14, 2026-09-15. The affected weekly rate is **incomplete**, not a reliably full-week rate.
- The only available date field is **order creation time**, not return/delivery event time. Weekly rates are **order-created cohorts with their recorded final status**, not returns occurring that week. Outcome snapshot time is undocumented, so right-censoring is possible.

## Answer 1: Weekly COD return rates (literal all 26 merchant IDs)

| Week (IST) | Returned | Delivered | Final COD | Return rate | Coverage |
|:---|---:|---:|---:|---:|:---|
| 2026-07-27 to 2026-08-02 | 1,165 | 2,638 | 3,803 | 30.63% | Observed 7d |
| 2026-08-03 to 2026-08-09 | 1,093 | 2,696 | 3,789 | 28.85% | Observed 7d |
| 2026-08-10 to 2026-08-16 | 1,162 | 2,601 | 3,763 | 30.88% | Observed 7d |
| 2026-08-17 to 2026-08-23 | 1,179 | 2,717 | 3,896 | 30.26% | Observed 7d |
| 2026-08-24 to 2026-08-30 | 1,090 | 2,538 | 3,628 | 30.04% | Observed 7d |
| 2026-08-31 to 2026-09-06 | 1,113 | 2,514 | 3,627 | 30.69% | Observed 7d |
| 2026-09-07 to 2026-09-13 | 1,155 | 2,712 | 3,867 | 29.87% | Observed 7d |
| 2026-09-14 to 2026-09-20 | 797 | 1,784 | 2,581 | 30.88% | ⚠ GAP |
| 2026-09-21 to 2026-09-27 | 1,137 | 2,613 | 3,750 | 30.32% | Observed 7d |
| 2026-09-28 to 2026-10-04 | 1,108 | 2,606 | 3,714 | 29.83% | Observed 7d |
| 2026-10-05 to 2026-10-11 | 1,079 | 2,715 | 3,794 | 28.44% | Observed 7d |
| 2026-10-12 to 2026-10-18 | 1,103 | 2,520 | 3,623 | 30.44% | Observed 7d |
| 2026-10-19 to 2026-10-25 | 1,158 | 2,521 | 3,679 | 31.48% | Observed 7d |

> Each week is based on **created_at converted to IST**. `2026-09-14` and `2026-09-15` have no orders across any merchant, making the September 14 week incomplete. The week's rate is an *observed-subset* rate and should not be treated as an uncontaminated full-week statistic.

A production-only weekly view is provided in `results/weekly_cod_production_only.csv` to disclose the effect of removing obvious test-store IDs.

## Answer 2: The top 3 stores (at least 200 final-outcome COD orders)

### Literal assignment interpretation: include all 26 IDs

| Rank | Store | Returned COD | Final COD | Return rate |
|---:|:---|---:|---:|---:|
| 1 | `M_TEST_01` | 773 | 871 | 88.75% |
| 2 | `M_TEST_02` | 513 | 582 | 88.14% |
| 3 | `M122` | 778 | 1,968 | 39.53% |

Two stores contain `TEST` in their IDs. They have **not** been silently excluded from the literal result.

### Business interpretation: exclude named test accounts

| Rank | Production store | Returned COD | Final COD | Return rate |
|---:|:---|---:|---:|---:|
| 1 | `M122` | 778 | 1,968 | 39.53% |
| 2 | `M108` | 969 | 2,495 | 38.84% |
| 3 | `M110` | 992 | 2,601 | 38.14% |

The **test-merchant exclusion is an assumption inferred from the merchant IDs**, not corroborated by a store master table; confirm with the business before using the production-only view as an official KPI. `M117` fails the 200-order minimum even though its rate is high. The full list, including ineligible stores, is in the ranking CSVs.

## Answer 3: Complete observed data audit and action log

| Severity | Check or finding | Count | Treatment |
|:---|:---|---:|:---|
| HIGH | Duplicate order_id records | 1,439 | Remove exact duplicate extra rows; one vote per distinct order_id. |
| HIGH | Conflicting records for the same order_id | 0 | Quarantine all versions of conflicting IDs, never pick an arbitrary winner. |
| HIGH | Missing created_at | 287 | Exclude from weekly trend; include in all-time store rank if payment/status/merchant are valid. |
| HIGH | Invalid or unzoned created_at | 0 | Same treatment as undated; warn separately. |
| HIGH | Zero-order days across all stores (IST) | 2 | Flag affected weeks as incomplete; do not assume zero real-world demand. |
| HIGH | Likely test merchants | 2 | Publish literal all-merchant results AND separate production-only sensitivity; do not silently drop. |
| HIGH | Missing delivery/return event-time columns (schema fields) | 2 | Cannot attribute actual return events to their occurrence week; report created-at cohorts only. |
| HIGH | Missing extract/as-of timestamp (schema field) | 1 | Cannot independently establish outcome maturity or when statuses were observed. |
| MEDIUM | No authoritative test/production store flag (schema field) | 1 | Test exclusion is an explicitly labelled sensitivity based only on merchant ID patterns. |
| MEDIUM | Status labels needing normalization | 11,234 | Strip whitespace and standardize case; RTO maps to returned, delivered maps to delivered. |
| MEDIUM | Payment labels needing normalization | 6,740 | Map cod, COD and Cash on Delivery to COD; ignore non-COD for the requested metric. |
| MEDIUM | Order weeks changed by UTC to IST conversion | 2,990 | Convert timestamp to Asia/Kolkata before Monday-to-Sunday grouping. |
| MEDIUM | COD orders with non-final status | 7,799 | Exclude pending, in_transit and cancelled from the denominator. |
| MEDIUM | Merchants below 200 final-outcome COD orders | 1 | Show in store audit table, but disqualify from top three. |
| LOW | Suspicious order_value >= 1,000,000 | 3 | Flag as possible sentinel/outlier; rate counts orders, never values, so retain. |
| INFO | RTO records with non-COD payment | 1,073 | Legitimate possible prepaid returns; exclude by COD-only definition (not flagged invalid). |
| INFO | Undated final-outcome COD orders | 150 | Included in store lifetime rankings; cannot be assigned to a specific week. |
| INFO | Unknown payment categories | 0 | Exclude from COD metric and flag for mapping review. |
| INFO | Unknown outcome categories | 0 | Exclude from final-outcome denominator and flag for mapping review. |
| INFO | Missing order identifiers (rows) | 0 | Cannot reliably deduplicate; exclude and flag. |
| INFO | Missing merchant identifiers (unique orders) | 0 | Exclude from merchant and weekly report and flag. |
| INFO | Timestamps outside declared assignment period | 0 | Exclude from specified weekly period; leave in all-time ranking with disclosure. |
| INFO | Invalid order_value | 0 | Flag but keep record in count-based return metric. |
| INFO | Nonpositive order_value | 0 | Flag but keep record in count-based return metric. |

**Data completeness and definition limits:**

1. No `delivered_at`, `returned_at`, delivery-attempt history or snapshot timestamp. Cannot compute *returns occurring during each week*, actual return delays, full cohort maturity, or distinguish late returns from final delivered outcomes.
2. `status='rto'` is treated as **returned to the store**. Confirm business interpretation; RTO can be operationally different from a customer return after delivery.
3. No independent store master, so `M_TEST_01` and `M_TEST_02` are **suspected** test accounts based on IDs, not verified test environments.
4. A complete-looking date is not proof of complete ingestion. Two **globally empty** IST dates are observed, but the actual upstream missing-order volume cannot be recovered.
5. Missing `created_at` cannot be imputed safely; those orders stay in store-level aggregates only.
6. Non-COD RTO records can be legitimate. They are excluded for **metric scope**, not deleted as bad orders.
7. `order_value` is not part of this order-count-based metric. Three conspicuous high values are retained, flagged, and have **no effect** on rates.
8. Any recent week may have unresolved shipments. Excluding pending/in-transit is exactly what the formula requires, but older and newer weekly cohorts may have different completion maturity. Therefore rates are descriptive, not a causal trend claim.
9. Raw status/payment spelling variants were mapped only through an explicit, documented rule; unknown values would be flagged, not guessed.

## Reproducibility and checks

```bash
python3 part2/analyze_orders.py --input part2/orders.csv --output part2/results
python3 -m unittest discover -s part2/tests -v
```

Files: weekly results (all and production-only), full merchant rankings (all and production-only), daily coverage, quality issues, metrics JSON, and a self-contained HTML dashboard. Internal assertions reconcile all weekly and merchant COD numerators and denominators to their underlying records.

**Trust verdict:** Store-level counts are reproducible **conditional on supplied records and definitions**. The September 14 cohort week is **known incomplete**. Test-account treatment and outcome-event dating require a business definition or upstream data before an official production return-rate dashboard is certified.
