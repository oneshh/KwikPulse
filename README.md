# KwikPulse | Part 3: Handover

[**Repository**](https://github.com/oneshh/KwikPulse) · [**Live news tracker**](https://oneshh.github.io/KwikPulse/) · [**Live COD analysis**](https://oneshh.github.io/KwikPulse/part2/) · [**Detailed Part 2 findings**](part2/results/findings.md)

## Run it / what runs when

From the repository root (Python 3.9+):

```bash
pip install -r requirements.txt
python collector.py
python -m http.server 8000 --directory docs   # localhost:8000
```

Part 2 uses only the Python standard library and the committed `part2/orders.csv`:

```bash
python part2/analyze_orders.py --input part2/orders.csv --output part2/results
python part2/verify_with_sqlite.py --input part2/orders.csv --output part2/results
python -m unittest discover -s part2/tests -v
python part2/publish_dashboard.py
```

- **Part 1:** `Daily News Tracker` runs on GitHub Actions **daily at 03:17 UTC / 08:47 IST**, or manually. It fetches Google News RSS, filters and deduplicates mentions of GoKwik, Shopflo, Simpl and Razorpay Magic Checkout, commits historic data under `docs/data/` and deploys `docs/` to GitHub Pages. Failed/empty runs create a GitHub Issue.
- **Part 2:** `Part 2 | COD Data Quality Validation` runs on relevant pushes/PRs or manual dispatch. It executes **35 tests**, recomputes reports, checks counts independently in SQLite and fails on report drift. **It does not fetch fresh orders or run daily.**

## What breaks first / how I would find out

1. **RSS variability:** missing items, false positives or syndication inflate/deflate share. Check Actions logs, alert Issues, `docs/data/status.json`, daily volume changes and sampled headlines. Successful runs do **not** guarantee full coverage.
2. **A scheduled run never starts:** GitHub delays or disables schedules, and the workflow cannot self-alert if never triggered. Check Actions last-run time; add an independent heartbeat.
3. **Order data quality:** missing days, duplicate conflicts, changed labels or stale exports. Review `part2/results/data_quality_issues.csv`, week-gap flags, failing tests and SQLite reconciliation. Missing return-event timestamps and unverified test stores are **upstream limitations**.

## With two more days

**Day 1:** Canonical publisher links/headlines; source-level RSS anomaly checks; external missed-run alert.  
**Day 2:** Approved scheduled orders export; freshness/schema/volume quality gates; verified test-store lookup and `returned_at`, `delivered_at`, `extract_as_of` fields; separate event-week returns from creation-week cohorts.

## Part 2: three answers

**1. Weekly COD return rates** (IST Monday start, 2026, all 26 IDs): Jul 27 **30.63%**; Aug 3 **28.85%**; Aug 10 **30.88%**; Aug 17 **30.26%**; Aug 24 **30.04%**; Aug 31 **30.69%**; Sep 7 **29.87%**; Sep 14 **30.88%***; Sep 21 **30.32%**; Sep 28 **29.83%**; Oct 5 **28.44%**; Oct 12 **30.44%**; Oct 19 **31.48%**. *Sep 14 week has a two-day upstream gap.* Rate = COD RTO / (COD RTO + COD delivered), grouped by **order creation week**, not return-event week.

**2. Top three** (≥200 final COD orders): **M_TEST_01 88.75%, M_TEST_02 88.14%, M122 39.53%**. Excluding *suspected* test accounts: **M122 39.53%, M108 38.84%, M110 38.14%**. Business must confirm test status.

**3. Data audit:** **97,378** raw rows; **1,439** excess exact duplicates removed → **95,939** unique orders; **287** undated orders excluded from weekly rates; Sep 14–15 globally empty and flagged; payment/status labels normalized, timestamps shifted to IST before grouping, unfinished COD outcomes excluded, test IDs separately reported. Overall rate **30.20%** (all IDs) / **28.37%** (excluding suspected tests). [Full RCA](part2/results/findings.md).

**Limits:** Google News RSS is not exhaustive; the orders file cannot establish *when* returns occurred or whether the latest cohorts are mature.
