# Code walkthrough and RCA defence guide

This explains **why** the code makes its decisions and what happens if an evaluator supplies a harder CSV. The primary metric remains `COD RTO / (COD RTO + COD delivered)` for Monday–Sunday **IST creation-date cohorts**.

## The 5-layer control design

1. **Input contract (`analyze_orders.read_and_audit`)**: verify exact required headers, reject broken field counts, fingerprint the untouched source, capture unique IDs, detect and quarantine contradictory duplicates, and normalize only explicit known labels. Unknown payments/statuses never get silently mapped into the denominator. Blank or unzoned dates do not become arbitrary dates.
2. **Business definitions (`build_weekly`, `build_store_rankings`)**: convert UTC to IST before week grouping; exclude cancelled, pending and in-transit orders; apply the >=200 rule to **final COD outcomes**; retain undated final COD orders for all-period store ranking but not weekly reporting. Test-store exclusion is an explicitly separate scenario.
3. **Quantified decision impact (`rca_diagnostics.raw_scenarios`)**: recompute seven precisely named variants. A naive case-sensitive no-dedup calculation gives **30.1305%**, a normalized no-dedup calculation **30.1973%**, and the correctly deduplicated literal result **30.1989%**. Removing suspected test stores lowers it to **28.3655%**. Changes are published in **percentage points**, not vaguely described as 'big/small'.
4. **RCA traceability (`rca_diagnostics.source_evidence`, `merchant_diagnostics`, `merchant_week_matrix`)**: keep original line examples, show 338 merchant-week cohort rows, report unresolved-order exposure and undated-order sensitivity per store, and warn about small denominators. Wilson 95% intervals are an optional **descriptive** indication of sample uncertainty; they cannot fix missing records or biased final-outcome selection.
5. **Verification (`assert_invariants`, `rca_diagnostics.assertions`, `verify_with_sqlite.py`, `tests/`)**: source-to-unique ledger, cross-grain reconciliations, exact rational tie sorting, 35 synthetic edge-case tests, and an independently implemented SQLite recalculation.

## Issue → protection → file showing evidence

| What can go wrong? | Protection / RCA behavior | Source or output |
|---|---|---|
| Same order counted twice | Exact copies removed; conflicting versions quarantined rather than picked arbitrarily | `analyze_orders.py`, `reconciliation_ledger.csv`, `exception_evidence.csv` |
| COD written in several styles | Canonicalize only known spellings; compare naive and normalized answers | `canonical_payment`, `metric_sensitivity.csv` |
| Status has spaces/case variation | Canonicalize, count only final outcomes | `canonical_status`, `metric_sensitivity.csv` |
| Time zone shifts Sunday night to Monday | Parse explicit offset to Asia/Kolkata *before* week assignment | `parse_instant`, unit boundary tests |
| A test account dominates top three | Keep the 26-ID answer; publish non-test sensitivity; confirm via merchant master | `store_rankings_*.csv`, `merchant_rca.csv` |
| Two whole days absent | Flag week as incomplete; never invent orders or 'corrected' percentages | `daily_rca.csv`, `weekly_cod_*.csv` |
| One day populated solely by test rows | Production-only weekly coverage detects its own missing day | `build_weekly` filtered gap logic, regression test |
| Timestamp missing but order otherwise valid | Retain in store total; exclude from weekly cohort; quantify rate effect | `metric_sensitivity.csv`, `merchant_rca.csv` |
| Order sits in pending/in-transit | Exclude from denominator, disclose unresolved share by store and week | `merchant_rca.csv`, `merchant_weekly_rca.csv` |
| Merchant has a spectacular rate on too few orders | Apply 200 **final-COD** threshold, still show store in full audit | `store_rankings_*.csv`, threshold tests |
| Identical percentages with different sample size | Sort on exact rational ratio; deterministic tie-break on denominator then ID | `build_store_rankings`, exact-fraction regression test |
| Zero final COD orders | Return rate undefined/blank, **never zero** | `pct`, `wilson_interval`, zero-denominator tests |
| Out-of-range or invalid date | Flag; exclude invalid date from weeks; add period-scope sensitivity | `read_and_audit`, `metric_sensitivity.csv` |
| Huge order amount looks corrupt | Flag amount, retain order in order-count rate | `data_quality_issues.csv`, `exception_evidence.csv` |
| RTO paid by UPI/card | Do not treat as COD RTO; do not call it invalid data | `read_and_audit`, non-COD RTO tests |
| Merchants have differing open-order shares | Report maturity diagnostic rather than claim point estimates are fully comparable | `merchant_rca.csv`, `merchant_weekly_rca.csv` |
| Deceptively 'complete' nonzero dates | Label coverage as observed only, not source-certified | `RCA_DEEP_DIVE.md` |
| Reviewer disputes any exclusion | Reproduce the result with the clearly labeled scenario, avoiding hidden assumptions | `metric_sensitivity.csv` |

## Where the original dataset still cannot support a definitive answer

- **No `returned_at` or `delivered_at`:** these are creation-week *cohort* outcomes, not actual return events in a calendar week.
- **No extraction snapshot time or event history:** more recent cohorts could still resolve, and a recorded `delivered` status may not encode later customer returns.
- **No authoritative merchant dimension:** `M_TEST_*` are suspected test accounts based on identifiers, not verified classification.
- **No upstream completeness log:** the 14–15 September zero rows are observed, but the cause and number of missing orders are unknowable from this CSV alone.

**Trust status:** arithmetic = verified conditional on source; complete operational weekly KPI = not yet certifiable. The appropriate next action is to obtain source event timestamps, a frozen as-of extract, a merchant master, and ingestion/reconciliation logs, then rerun the same pipeline. These are deliberate 'cannot infer' findings, not unhandled exceptions.

## Run (from repository root)

```bash
python3 part2/analyze_orders.py
python3 -m unittest discover -s part2/tests -v
python3 part2/verify_with_sqlite.py
python3 part2/publish_dashboard.py
```

All outputs are deterministic from `part2/orders.csv` and the supplied command-line period/threshold. `part2/results/quality_gates.csv` records all additional reconciliation assertions.
