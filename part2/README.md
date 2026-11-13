# KwikPulse | Part 2: Can these numbers be trusted?

**Standalone, reproducible assessment submission.** Everything is inside `part2/` so the existing KwikPulse Part 1 app, scheduled collector, requirements, and GitHub Pages deployment remain unchanged.

> **The question:** Weekly cash-on-delivery (COD) return rate across Monday-to-Sunday **India Standard Time** weeks, highest-return-rate stores with **at least 200 final-outcome COD orders**, and a complete account of data quality issues and how they were treated.

## Answers at a glance

| Question | Result |
|:--|:--|
| Source | **97,378 CSV rows**, 26 unique merchant IDs, 27 July–25 October 2026 IST |
| Unique order IDs after removing exact duplicates | **95,939** (1,439 redundant rows removed) |
| All-ID COD return rate | **30.20%** (14,394 returned / 47,664 final-outcome COD) |
| Non-test COD return rate | **28.37%** (13,108 returned / 46,211 final-outcome COD) |
| Top 3, literal 26 merchant IDs | **M_TEST_01 88.75%; M_TEST_02 88.14%; M122 39.53%** |
| Top 3, excluding named test merchants | **M122 39.53%; M108 38.84%; M110 38.14%** |
| Known incomplete week | **14–20 September 2026**. Zero timestamped orders across all merchants on Sep 14 and 15. |
| Missing created_at | **287** distinct orders; **150** are final-outcome COD records |
| Independent verification | **35 unit tests passing**, plus independent SQLite group-by checks on all 13 weeks and all merchants |

The **literal assignment answer includes all 26 IDs**. Because two merchants explicitly have `TEST` in their IDs, a **separate business-friendly production-only sensitivity** is also supplied, rather than silently dropping test stores. No store master file is available to verify their classification.

## Explore the answer

Open **`index.html`** in a browser for the full offline dashboard. Use the toggle to compare the 26-ID literal scope against 24 non-test stores. Export relevant weekly or store ranking tables directly from the dashboard.

The text-only, fully explained submission is **`results/findings.md`**. It lists the full weekly table, both top-three rankings, every observed issue and all caveats.

## Reproduce from source

Run from the **root of the existing `KwikPulse` repository**, using Python 3.9+ (no external dependencies):

```bash
python3 part2/analyze_orders.py --input part2/orders.csv --output part2/results
python3 part2/publish_dashboard.py
python3 -m unittest discover -s part2/tests -v
python3 part2/verify_with_sqlite.py --input part2/orders.csv --output part2/results
```

The first command writes output files and regenerates `part2/index.html`. The second mirrors the dashboard and downloadable CSVs into the current Pages source directory without touching Part 1. The third checks 35 synthetic edge cases. The fourth independently recomputes **all** weekly and store COD numerator/denominator counts in SQLite directly from the original CSV, confirming the CSV deliverables match.

## Definition and assumptions

1. Convert timestamps to `Asia/Kolkata`, **then** take Monday to Sunday, with weeks labelled by Monday's date. Time-zone conversion moves 2,990 records into different weekly cohorts compared with naive UTC grouping.
2. Deduplicate using `order_id`, removing redundant **exact** copies. If a future file has conflicting records with the same ID, quarantine all versions rather than assume which one is correct.
3. Normalize payment labels (`cod`, `COD`, `Cash on Delivery`) and outcome labels (case and whitespace variants). The submitted file contains 6 original payment labels and 20 original status labels; none remain unknown after mapping.
4. Count only `COD` and **final delivery outcome**: `rto` means returned to origin/store; `delivered` means delivered. Denominator is `rto + delivered`, not all COD. `pending`, `in_transit`, and `cancelled` are excluded. Confirm with the business that RTO is the intended meaning of “returned to the store.”
5. A missing `created_at` prevents weekly assignment. These orders are retained for **all-dataset store rankings** when store, payment, and outcome are otherwise known, because the store-level question does not specify a date filter beyond the supplied file. They are excluded from week-by-week rates.
6. Rank only merchants with **at least 200** final-outcome COD orders; a very high rate below this threshold does not qualify.
7. Calculate the exact ratio from integers and round the **displayed** percentage to two decimals only at output, avoiding averaging weekly percentages or order values.
8. Use all 26 IDs as the literal primary answer; additionally show a 24-ID non-test view. The `TEST` exclusion is a documented, unverified business assumption.

**Important distinction:** `created_at` is the **order creation date**. The CSV has no `returned_at`, `delivered_at`, shipment history, or snapshot timestamp. Therefore we can calculate **creation-week cohorts based on their recorded outcomes**; we **cannot** claim to know the number of actual return events that occurred in a calendar week. Recent cohorts may still be awaiting final outcomes. In addition, Sep 14–15 have no timestamped records anywhere in the source, so the week of Sep 14–20 must carry an explicit **data-gap warning**.

## Repository files

```text
part2/
├── README.md                       # Scope, summary, methodology, usage
├── SUBMISSION_SUMMARY.md           # A concise answer to the three numbered questions
├── orders.csv                      # Original assignment file, unchanged bytes
├── analyze_orders.py               # Complete standard-library analysis and audit
├── verify_with_sqlite.py           # Independently recomputes and reconciles all metrics
├── index.html                      # Generated offline dashboard and downloadable tables
├── publish_dashboard.py            # Copy dashboard to existing docs/part2 Pages directory
├── tests/
│   └── test_analysis.py            # 18 synthetic edge-case unit tests
└── results/
    ├── findings.md                # Detailed written answer and trust verdict
    ├── weekly_cod_all_merchants.csv
    ├── weekly_cod_production_only.csv
    ├── store_rankings_all_merchants.csv
    ├── store_rankings_production_only.csv
    ├── daily_coverage.csv
    ├── data_quality_issues.csv
    └── metrics.json               # Source hash, audit totals and reconciliation counts

docs/part2/                          # Pages-ready copy; leaves Part 1 docs untouched
├── index.html
└── results/                         # Dashboard downloadable tables and notes
```

## What is and isn't trustworthy

- **Trustworthy within the supplied source:** deduplicated store-level counts and weekly *observed order cohorts* under the explicit mapping rules; source-to-output arithmetic is independently verified.
- **Not trustworthy as complete weekly operations:** 14–20 September's full-week picture, because 14–15 September have no recorded orders from any of the 26 merchants.
- **Needs upstream/business confirmation:** whether named `M_TEST` merchants count as stores, whether `rto` is exactly the defined return, final-outcome snapshot timing, possible late-updated statuses, and the source of the two-day global data gap.
- **Cannot be derived from this CSV:** the actual *week a parcel was returned*, final resolution dates, time to return, verified shipment-delivery timelines, or any corrected returns for missing upstream records.

**No arbitrary orders were deleted for high monetary value.** Three conspicuous `order_value = 9,999,999` records remain in the analysis: the metric counts orders, not money. There are also 1,073 **prepaid** RTO records, which may be perfectly valid returns but are not COD, and hence do not count.

## Practical upload to the existing repository

Upload **both the `part2/` and `docs/part2/` folders** from this package into the root of `https://github.com/oneshh/KwikPulse`, preserving their paths. Do **not** replace the existing `docs/index.html`, `.github/workflows/news-tracker.yml`, `collector.py`, or Part 1 data.

The existing GitHub Actions workflow deploys the contents of `docs/` to GitHub Pages. After you commit the new folders and re-run **Actions → Daily News Tracker → Run workflow** (or await the next successful run), the new report should be available at **`https://oneshh.github.io/KwikPulse/part2/`**, while the Part 1 home dashboard remains unchanged. This URL is a deployment target, **not** a claim that the page is currently live.

## No external dependencies

The implementation uses only Python's standard-library modules `csv`, `collections`, `datetime`, `zoneinfo`, `decimal`, `hashlib`, `json`, `sqlite3`, `unittest`, and `argparse`.


## Deep RCA extension (enhanced submission)

The original three answers and 24 baseline audit checks remain unchanged. `rca_diagnostics.py` now runs automatically inside `analyze_orders.py` and adds seven files to `part2/results/` plus an RCA explanation and run manifest. See **[`CODE_REVIEW_AND_EDGE_CASES.md`](CODE_REVIEW_AND_EDGE_CASES.md)** for a concise review of edge cases and code behavior, and **[`results/RCA_DEEP_DIVE.md`](results/RCA_DEEP_DIVE.md)** for measured impacts and unresolved source limitations.

New diagnostics:

- `metric_sensitivity.csv`: seven processing choices (including naive raw, deduplicated, test-excluded and dated-only), numerators/denominators and precise percentage-point differences.
- `merchant_rca.csv`: 26 merchant profiles with open-order shares, undated sensitivity, sample size, and conditional Wilson intervals.
- `merchant_weekly_rca.csv`: 338 store-week groups, each with outcome mix, missing-day flags, and small-sample flags.
- `daily_rca.csv`: daily volume benchmark; absence of source records is **not** imputed as a real zero-sales day.
- `exception_evidence.csv`: first five original CSV line examples for each observed validation class.
- `reconciliation_ledger.csv` and `quality_gates.csv`: source-to-output accounting and six extra cross-grain checks.
- `RCA_RUN_MANIFEST.json`: input hash, computation scope, reproducibility facts and operational trust status.

**35 regression tests** cover the original cases plus scope sensitivity, exact fractional ranking ties, filtered-scope coverage, misleading zero-denominator rates, original-row evidence, and merchant maturity. Independent SQLite verification remains unchanged and still passes.

Business readiness stays **conditional**: the two completely absent IST dates, unverified TEST store classification, and missing outcome timestamps/as-of time must be resolved upstream. The code does not pretend otherwise.

## Reviewer-first navigation and automated checks

If you review only one document, open **[`EVALUATOR_GUIDE.md`](EVALUATOR_GUIDE.md)**. It connects each important data problem to the original evidence, decision and measurable effect without confusing a data defect with an unverified business assumption.

The separate **`.github/workflows/part2-validation.yml`** workflow runs 35 tests, rebuilds the analysis, verifies all weekly and merchant counts using independent SQLite queries, republishes the Part 2 dashboard, and **fails if committed reports drift** from the reproducible outputs. It uses read-only repository permissions and triggers only on Part 2 changes (or manually); it does not interfere with the Part 1 collector.
