# Part 2 · Submission summary

**Metric:** COD RTOs / (COD RTOs + COD delivered), by the order’s **created_at week in IST**. Exact duplicates removed; cancellations and open orders excluded.

## 1. COD return rate by week

| IST week (Mon–Sun) | COD returned | COD delivered | Final COD | Return rate | Data quality |
|:--|--:|--:|--:|--:|:--|
| 2026-07-27 to 2026-08-02 | 1,165 | 2,638 | 3,803 | **30.63%** | 7 recorded days |
| 2026-08-03 to 2026-08-09 | 1,093 | 2,696 | 3,789 | **28.85%** | 7 recorded days |
| 2026-08-10 to 2026-08-16 | 1,162 | 2,601 | 3,763 | **30.88%** | 7 recorded days |
| 2026-08-17 to 2026-08-23 | 1,179 | 2,717 | 3,896 | **30.26%** | 7 recorded days |
| 2026-08-24 to 2026-08-30 | 1,090 | 2,538 | 3,628 | **30.04%** | 7 recorded days |
| 2026-08-31 to 2026-09-06 | 1,113 | 2,514 | 3,627 | **30.69%** | 7 recorded days |
| 2026-09-07 to 2026-09-13 | 1,155 | 2,712 | 3,867 | **29.87%** | 7 recorded days |
| 2026-09-14 to 2026-09-20 | 797 | 1,784 | 2,581 | **30.88%** | ⚠ Incomplete: Sep 14–15 absent |
| 2026-09-21 to 2026-09-27 | 1,137 | 2,613 | 3,750 | **30.32%** | 7 recorded days |
| 2026-09-28 to 2026-10-04 | 1,108 | 2,606 | 3,714 | **29.83%** | 7 recorded days |
| 2026-10-05 to 2026-10-11 | 1,079 | 2,715 | 3,794 | **28.44%** | 7 recorded days |
| 2026-10-12 to 2026-10-18 | 1,103 | 2,520 | 3,623 | **30.44%** | 7 recorded days |
| 2026-10-19 to 2026-10-25 | 1,158 | 2,521 | 3,679 | **31.48%** | 7 recorded days |

All 26 IDs combined: **14,394 / 47,664 = 30.20%**. Non-test IDs: **13,108 / 46,211 = 28.37%**.

## 2. Top 3 stores, minimum 200 final-outcome COD orders

| Scope | Rank 1 | Rank 2 | Rank 3 |
|:--|:--|:--|:--|
| Literal, all 26 IDs | **M_TEST_01: 88.75%** (773/871) | **M_TEST_02: 88.14%** (513/582) | **M122: 39.53%** (778/1,968) |
| Excluding named test stores | **M122: 39.53%** (778/1,968) | **M108: 38.84%** (969/2,495) | **M110: 38.14%** (992/2,601) |

**Why two versions?** The ID names suggest two test stores. The assignment does not authorize silently excluding them, so the literal answer is primary and the production-only ranking is a transparent alternative. M117 is ineligible despite a 63.45% return rate because only 145 final-outcome COD orders meet the definition.

## 3. Problems found and actions taken

| Issue | Count | Action |
|:--|--:|:--|
| Duplicate order_id records | 1,439 | Remove exact duplicate extra rows; one vote per distinct order_id. |
| Missing created_at | 287 | Exclude from weekly trend; include in all-time store rank if payment/status/merchant are valid. |
| Zero-order days across all stores (IST) | 2 | Flag affected weeks as incomplete; do not assume zero real-world demand. |
| Likely test merchants | 2 | Publish literal all-merchant results AND separate production-only sensitivity; do not silently drop. |
| Missing delivery/return event-time columns (schema fields) | 2 | Cannot attribute actual return events to their occurrence week; report created-at cohorts only. |
| Missing extract/as-of timestamp (schema field) | 1 | Cannot independently establish outcome maturity or when statuses were observed. |
| No authoritative test/production store flag (schema field) | 1 | Test exclusion is an explicitly labelled sensitivity based only on merchant ID patterns. |
| Status labels needing normalization | 11,234 | Strip whitespace and standardize case; RTO maps to returned, delivered maps to delivered. |
| Payment labels needing normalization | 6,740 | Map cod, COD and Cash on Delivery to COD; ignore non-COD for the requested metric. |
| Order weeks changed by UTC to IST conversion | 2,990 | Convert timestamp to Asia/Kolkata before Monday-to-Sunday grouping. |
| COD orders with non-final status | 7,799 | Exclude pending, in_transit and cancelled from the denominator. |
| Merchants below 200 final-outcome COD orders | 1 | Show in store audit table, but disqualify from top three. |
| Suspicious order_value >= 1,000,000 | 3 | Flag as possible sentinel/outlier; rate counts orders, never values, so retain. |
| RTO records with non-COD payment | 1,073 | Legitimate possible prepaid returns; exclude by COD-only definition (not flagged invalid). |
| Undated final-outcome COD orders | 150 | Included in store lifetime rankings; cannot be assigned to a specific week. |

**Important schema limitations:** No delivered/returned event dates, no extraction/snapshot time, and no verified merchant classification. A creation-week *cohort* rate cannot establish the actual number of returns occurring that calendar week. Incomplete dates and unresolved status maturity also limit interpretation.

## Reproduce and independently check

```bash
python3 part2/analyze_orders.py
python3 -m unittest discover -s part2/tests -v
python3 part2/verify_with_sqlite.py
```

Full audit details and trust verdict: `results/findings.md`. Offline dashboard: `index.html`.


## Optional deep-dive: Why the metric changes (RCA extension)

The enhanced audit quantifies how processing choices affect the result, instead of simply listing defects:

| Scenario | Final COD | COD RTO | Return rate | Delta vs primary |
|:--|--:|--:|--:|--:|
| Naive case-sensitive / no deduplication | 37,467 | 11,289 | 30.1305% | -0.0684 pp |
| Labels normalized, duplicates retained | 48,352 | 14,601 | 30.1973% | -0.0016 pp |
| **Primary literal answer** | **47,664** | **14,394** | **30.1989%** | **0.0000 pp** |
| Exclude suspected test accounts | 46,211 | 13,108 | 28.3655% | -1.8334 pp |
| Exclude undated orders | 47,514 | 14,339 | 30.1785% | -0.0204 pp |

Extra outputs document original-row evidence, 338 merchant-week groups, missing-data and open-order exposure by store, precise eligibility and ranking ties, and six additional source-to-output reconciliations. The code now has **35 passing tests**; every main weekly and store total still matches an independent SQLite calculation.

Full review: `CODE_REVIEW_AND_EDGE_CASES.md` and `results/RCA_DEEP_DIVE.md`. These checks improve the **defensibility** of the numbers; they do not fill missing source records or create event timestamps.
