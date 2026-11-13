# Part 2 | Evaluator's one-page guide

**Start here if you are reviewing correctness rather than code length.** The supplied CSV is intentionally imperfect; none of the numbers below is presented as a verified complete view of all real-world orders. Reproduce them by running the commands at the end of this page.

## Answers, with the precise counting rules

- **Primary metric:** COD `rto` / (COD `rto` + COD `delivered`), after deduplicating exact `order_id` copies and normalizing category labels. No averaging weekly percentages, no weighting by amount. Weekly cohorts are assigned by **order `created_at` converted to Asia/Kolkata**, Monday to Sunday.
- **All 26 IDs:** 14,394 / 47,664 = **30.20%** overall, counting final-COD orders with a missing creation timestamp in this all-period calculation.
- **Production-only sensitivity (not the literal answer):** 13,108 / 46,211 = **28.37%**, excluding `M_TEST_01` and `M_TEST_02` only *as a clearly labelled assumption*.
- **Top three, literal eligibility of at least 200 final-outcome COD orders:** `M_TEST_01` (773/871, 88.75%), `M_TEST_02` (513/582, 88.14%), `M122` (778/1,968, 39.53%).
- **Top three, named test IDs excluded:** `M122` (778/1,968, 39.53%), `M108` (969/2,495, 38.84%), `M110` (992/2,601, 38.14%). Both sets are in the results; no silent merchant exclusion.
- **13 week-level rates:** see `results/weekly_cod_all_merchants.csv` or `results/findings.md`. The partial-coverage week **14–20 Sep** is marked as such. Daily source absence ≠ real zero transactions.

## The audit decisions that matter most

| Observable issue or limitation | Evidence | Action, and why |
|---|---|---|
| Duplicate record inflation | 1,439 additional exact copies of an `order_id` | Count each order only once; quarantine *conflicting* versions if encountered. Exact duplicates move the all-store rate by just ~0.0016 percentage points, but can still bias individual groups. |
| Inconsistent category spelling | 6 original payment labels, 20 original status labels | Normalize case/whitespace and map known COD aliases; retain and flag any novel category rather than guessing it is final. |
| Wrong time zone would change cohort | 2,990 orders cross a Monday-week boundary from UTC to IST | Convert timestamps first, then derive Monday–Sunday buckets. |
| Missing creation dates | 287 distinct orders, 150 final COD | Exclude from **weekly** denominators; retain in **all-period merchant** denominators when otherwise valid; reconcile the difference transparently. |
| Whole days with no records | 14 & 15 Sep 2026 across all 26 merchants | Flag week as **incomplete**, do not invent missing orders or a corrected return rate. Root cause requires source/ETL logs. |
| Named test merchants | 2 with return rates above 88% | Give both the literal all-ID answer and an explicitly labelled non-test analysis. A verified production flag is absent. |
| Some stores have very few qualifying orders | M117 has 145 final COD | Show in audit, exclude only from eligible top-three ranking (threshold ≥200). |
| Non-final COD statuses | 7,799 pending/in-transit/cancelled COD orders | Exclude from final-outcome denominator; keep counts to show incomplete outcome maturity. |
| High monetary values | Three 9,999,999 values | Flag as possible outliers but do not suppress count-based order outcomes; return rate is not revenue-weighted. |
| Only `created_at`, no outcome event time or snapshot time | Missing schema dimensions | Describe **creation-week cohorts with recorded outcomes**, *not actual calendar-week returns* or fully matured cohorts. |

These are not all equivalent. **Confirmed source issues** include duplicates and missing timestamps; **unverified business assumptions** include test-store classification and the exact lifecycle semantics of `rto`; **limitations of this extract** include absent delivery/return event times and absent source snapshot date. The reports keep those categories separate.

## Targeted checks that prevent false confidence

- `results/metric_sensitivity.csv` quantifies seven raw / normalized / deduplicated / test-excluded / dated-only choices, rather than claiming every anomaly changes the rate materially.
- `results/merchant_weekly_rca.csv` covers **26 merchants × 13 creation weeks = 338 groups**; inspect non-final outcome share and small cohorts before drawing merchant-specific operational conclusions.
- `results/exception_evidence.csv` records **43 sampled original CSV line references** for review. It does **not** claim to enumerate every affected row.
- `results/reconciliation_ledger.csv`, `results/quality_gates.csv`, and a separate `verify_with_sqlite.py` make cross-grain and source-vs-output checks reproducible.
- **Top-three robustness:** dropping the undated orders without altering any other rule keeps the same three merchants in both the all-ID and named-test-excluded rankings, while slightly changing their rates. This is a sensitivity observation, not permission to discard those orders.
- **No false reconstruction:** two missing dates cannot be corrected from this CSV alone; a complete source event history, merchant master, and extract snapshot are needed for the unresolved business questions.

## Reproduce locally

From the root of the existing KwikPulse repository (Python 3.9+; **no external dependencies**):

```bash
python3 -m unittest discover -s part2/tests -v
python3 part2/analyze_orders.py --input part2/orders.csv --output part2/results
python3 part2/verify_with_sqlite.py --input part2/orders.csv --output part2/results
python3 part2/publish_dashboard.py
```

A **read-only, separately scoped GitHub Actions workflow** lives at `.github/workflows/part2-validation.yml`: it runs those tests and calculations on Part 2 changes and fails if committed outputs no longer match the regenerated files. The existing Part 1 news collector and homepage remain untouched.

## Trust verdict

The formulas, classification choices, and arithmetic are auditable **within the provided extract**. The week of **14–20 September** is explicitly data-incomplete; classification of named test IDs and the exact `rto` business definition require confirmation. With no delivery/return event time or as-of time, no one can honestly prove *actual return-event-week rates* or fully matured recent cohorts using this CSV alone.
