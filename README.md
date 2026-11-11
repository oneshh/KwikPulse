# KwikPulse — Part 1: Automated news tracker

Tracks GoKwik, Shopflo, Simpl and Razorpay Magic Checkout on a free GitHub Actions schedule, publishes a GitHub Pages dashboard, stores unique historical article records, and opens a GitHub Issue when a job fails or receives no usable RSS data.

## Setup

1. Create a **public** GitHub repository.
2. Upload all files including `.github/workflows/news-tracker.yml`, preserving directories.
3. Repository **Settings → Pages → Build and deployment → Source: GitHub Actions**.
4. Open **Actions → Daily News Tracker → Run workflow**, leave `simulate_failure` unchecked and start it.
5. Confirm a successful workflow, a Pages site URL and updated `docs/data/articles.json`.
6. For evidence: run the workflow with `simulate_failure` checked. The expected run fails and opens one GitHub Issue. Screenshot the failed run and Issue; then run the normal workflow again.

## How it works

- **Collection:** A Google News RSS search is made for each named company. No paid key is used. For Simpl the query adds checkout/payments/fintech context to limit false matches. Search results are *not* an exhaustive census of media coverage, and changing feeds, indexing, brand ambiguity or RSS terms can influence counts. Check source usage terms before commercial deployment; this is an evaluation prototype.
- **Identity:** The Google News RSS article URL is hashed to a stable ID. Re-reading the same URL across runs does not add duplicates. Different URLs for the same syndicated article may still be counted separately; a production implementation would resolve canonical publisher URLs and additionally deduplicate syndicated headlines.
- **History:** `docs/data/articles.json` is committed back to the repository, so it survives fresh Actions runners. Runs add or update records rather than replacing history.
- **Weekly share:** Articles are grouped using the publication date converted to **Asia/Kolkata**, Monday–Sunday. A story that mentions two tracked companies and appears in both feeds is counted as one *company mention* for each. Denominator: all company-article mentions in the selected week. All four percentages sum to ~100%. This is *share of observed RSS coverage*, not true share of all online news.
- **Publication:** The workflow uploads `docs` to GitHub Pages and deploys it after updating data. No separate branch-based Pages build is required.
- **Alert:** Any failed workflow step, including a forced empty source or zero usable RSS items, creates an Issue if no identical open Issue exists. Healthy runs create no Issues. An RSS run with previously seen but otherwise valid articles is a success and does not alert. For email notification, watch the repository/Issues in GitHub notification settings. A run that never starts cannot create its own alert, so check Actions scheduling inactivity separately.

## Limitations and improvements

Google News RSS search is convenient for a zero-cost prototype but its RSS use restrictions and indexing/search behavior are not a production-grade coverage source. For deployment beyond evaluation, use approved publisher RSS feeds or a licensed news source. Not all published articles appear in the feeds, results may be recency-limited, dates may reflect feed metadata, and source errors need monitoring. GitHub may delay scheduled jobs, and public repository schedules can be disabled after 60 days of inactivity. Google News links can redirect rather than expose original publisher URLs.

## Run locally

`pip install -r requirements.txt` then `python collector.py`. Serve `docs/` with `python -m http.server 8000 --directory docs`. Open `http://localhost:8000`.
