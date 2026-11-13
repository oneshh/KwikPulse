# Deep-dive RCA | Additional safeguards and quantified impact

**Run this alongside** `results/findings.md`. This is a diagnostic supplement, not a replacement for the literal three assignment answers.

## Measurement-impact bridge

| Scenario | Processing choice | Returns | Final COD | Rate | Difference vs primary |
|---|---|---:|---:|---:|---:|
| A | Naive case-sensitive, no deduplication | 11,289 | 37,467 | 30.1305% | -0.0684pp |
| B | Normalized labels, no deduplication | 14,601 | 48,352 | 30.1973% | -0.0016pp |
| C | Primary: unique orders, all merchant IDs | 14,394 | 47,664 | 30.1989% | +0.0000pp |
| D | Sensitivity: exclude named test IDs | 13,108 | 46,211 | 28.3655% | -1.8334pp |
| E | Sensitivity: dated orders only | 14,339 | 47,514 | 30.1785% | -0.0204pp |
| F | Sensitivity: non-test and dated | 13,055 | 46,064 | 28.3410% | -1.8579pp |
| G | Sensitivity: dated AND within requested IST period | 14,339 | 47,514 | 30.1785% | -0.0204pp |

**Interpretation:** Removing duplicate rows changes the all-store COD return rate by only 0.0016 percentage points (the raw normalized scenario is -0.0016pp relative to the deduplicated primary). This small *aggregate* impact does **not** excuse double counting, because particular merchants or weeks might be differently affected. Suspected test-account classification produces a much larger change: **-1.8334 percentage points**. Retaining the 150 undated final-COD records changes the all-store result by -0.0204 points relative to dropping them.

## Additional RCA findings and safeguards

1. **Raw vs clean answers are now measurable.** A case-sensitive/no-dedup method, a normalized/no-dedup method, the literal primary, production-only, dated-only, and combined scope variations are all published in `metric_sensitivity.csv`. No silent switches.
2. **A two-day source-data gap is confirmed; the underlying cause is unknown.** Entire dataset dates with no timestamped orders: **2026-09-14, 2026-09-15**. Median *nonzero* daily volume is **1,070**. An ingestion failure is a hypothesis to investigate, not an established fact. This is context, **not** permission to impute the absent days or estimate a corrected return percentage.
3. **Merchant-week diagnostics expose localized blind spots.** `merchant_weekly_rca.csv` reports all 26 merchants across the requested 13 weeks, splitting COD into delivered, returned, pending, in transit, and cancelled, and flags small samples and the global gap. Sample-size warnings do not exclude orders from the assigned metric.
4. **Different merchants have different outcome maturity.** `merchant_rca.csv` reports open COD orders per store, the non-cancelled unresolved share, and the recorded denominator. More unresolved shipments can create biased cross-store comparisons even when every formula is correct.
5. **Undated orders are not dropped without disclosure.** There are **150** final-outcome COD orders missing `created_at`. Largest *store-level* rate shifts if undated final COD orders are excluded: M100: -0.1550pp, M105: -0.1181pp, M115: -0.1150pp.
6. **Small-sample uncertainty is visible, not confused with data accuracy.** `merchant_rca.csv` shows approximate Wilson 95% binomial intervals for observed outcomes. They are descriptive and assume independent, identically sampled observations; they **do not** resolve missing dates, incomplete cohorts, selection bias, or unclear merchant identity. The ranking still uses the assignment's point estimate and >=200 cutoff.
7. **Sample evidence is reproducible.** `exception_evidence.csv` lists the original CSV line and first examples for actual issue categories. A zero-count issue has no fabricated example; the file supports inspection and RCA.
8. **No arbitrary bad-data repair.** Contradictory duplicate IDs are quarantined instead of picking a status. Unknown status/payment cannot silently be classified as final COD. High order values are flagged but never remove a count-based return.
9. **Eligibility scope is explicit.** 1 store(s) below the minimum are excluded from the top-three rank, not from the comprehensive merchant audit.
10. **A record having a date is not proof of ingestion completeness.** Days with nonzero counts receive only an *observed coverage* designation. No historical delivery/return timestamps or snapshot date exist to establish mature, event-week RTO rates.

## Quality gates

| Gate | Result | Reason |
|---|---|---|
| Arithmetic reconciliation | **PASS** | Independent source count matches output |
| Cross-grain reconciliation | **PASS** | Store-week totals match main weekly table |
| Unambiguous all-merchant formula | **PASS, conditional** | RTO interpretation is explicitly assumed |
| Complete temporal coverage | **NEEDS UPSTREAM CHECK** | 2 completely empty IST days and 287 undated orders |
| Verified production-only merchant set | **NEEDS MERCHANT MASTER** | `TEST` name is not an authoritative dimension |
| Event-week or outcome-mature return rate | **NOT MEASURABLE** | Only `created_at` and an unknown snapshot state are supplied |

## RCA follow-up questions for a data engineer or operations lead

- Did the upstream ingestion/export job fail or filter out orders on **14 and 15 September**? Compare API calls, ETL logs, row-level source totals, and source-to-warehouse counts by IST date; re-export and re-run if recoverable.
- Are the merchants labelled `M_TEST_*` genuine non-production accounts? Confirm via the merchant master/environment dimension before adopting the filtered KPI.
- What exactly does `rto` mean in this platform, and are returns **after delivery** represented elsewhere? Validate status lifecycle and event timestamps.
- What is the extraction **as-of** time and what fraction of each created-week cohort is sufficiently aged? Re-run on a stable, maturity-defined window before comparing trends.
- Are missing timestamps random? Compare missing-date rate and missing-date return status by merchant; inspect source payloads to avoid assuming missingness is harmless.
- Are duplicate rows from repeated export batches, retrying ingestion, or non-idempotent writes? Use the original line references and IDs to trace their origin.

## Reproduce

```bash
python3 part2/analyze_orders.py
python3 -m unittest discover -s part2/tests -v
python3 part2/verify_with_sqlite.py
```

**Primary facts remain unchanged.** These diagnostics never impute missing transactions, never replace created-at with imaginary delivery timestamps, and never silently reinterpret the primary all-ID ranking.
