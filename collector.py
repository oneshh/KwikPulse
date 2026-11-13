"""Collect dated news mentions and maintain deduplicated historical coverage."""
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlencode

import feedparser
import requests

DATA_FILE = Path("docs/data/articles.json")
STATUS_FILE = Path("docs/data/status.json")
COMPANIES = {
    "GoKwik": '"GoKwik" (checkout OR ecommerce OR payments)',
    "Shopflo": '"Shopflo" (checkout OR ecommerce OR payments)',
    "Simpl": '"Simpl" (checkout OR payments OR fintech)',
    "Razorpay Magic Checkout": '"Razorpay" "Magic Checkout"',
}
NEWS_ENDPOINT = "https://news.google.com/rss/search"
def is_relevant(company, title):
    title = title.lower()

    if company == "Razorpay Magic Checkout":
        return (
            "razorpay" in title
            and "magic checkout" in title
        )

    if company == "GoKwik":
        return "gokwik" in title

    if company == "Shopflo":
        return "shopflo" in title

    if company == "Simpl":
        return (
            "simpl" in title
            and any(word in title for word in
                    ["checkout", "payment", "fintech", "pay later"])
        )

    return False


def load_existing():
    if not DATA_FILE.exists():
        return {}
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return {article["id"]: article for article in data if "id" in article}


def parse_date(entry):
    try:
        stamp = parsedate_to_datetime(entry.get("published", ""))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp.astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError, IndexError):
        # Don't fabricate publication dates: omit entries without usable dates.
        return None


def article_key(title, link):
    # Google News RSS provides a stable per-article entry ID when available;
    # here, use the full URL as a stable identity across daily fetches.
    normalized = link.strip().split("#", 1)[0]
    if not normalized:
        normalized = re.sub(r"\s+", " ", title.lower().strip())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]


def fetch_company(session, company, query):
    params = {"q": query, "hl": "en-IN", "gl": "IN", "ceid": "IN:en"}
    response = session.get(NEWS_ENDPOINT, params=params, timeout=30)
    response.raise_for_status()
    parsed = feedparser.parse(response.content)
    if parsed.bozo and not parsed.entries:
        raise RuntimeError(f"Malformed RSS response for {company}: {parsed.bozo_exception}")
    return parsed.entries


def main():
    if os.getenv("SIMULATE_EMPTY") == "1":
        raise RuntimeError("Test alert: simulated empty source results")
    existing = load_existing()
    
    # Revalidate previously stored article-company associations.
    for key, article in list(existing.items()):
        valid_companies = [
            company
            for company in article.get("companies", [])
            if is_relevant(company, article.get("title", ""))
        ]
    
        if valid_companies:
            article["companies"] = valid_companies
        else:
            del existing[key]

    fetched_count = 0
    valid_count = 0
    with requests.Session() as session:
        session.headers.update({"User-Agent": "KwikPulseAssignment/1.0 (RSS educational evaluation)"})
        for company, query in COMPANIES.items():
            entries = fetch_company(session, company, query)
            fetched_count += len(entries)
            for entry in entries:
                link = entry.get("link", "").strip()
                title = re.sub(r"\s+", " ", entry.get("title", "")).strip()
                publication = parse_date(entry)
                if not (link and title and publication):
                    continue
                if not is_relevant(company, title):
                    continue
                valid_count += 1
                key = article_key(title, link)
                if key not in existing:
                    source = entry.get("source", {})
                    existing[key] = {
                        "id": key, "title": title, "url": link,
                        "published_at": publication,
                        "source": source.get("title", "Unknown") if hasattr(source, "get") else "Unknown",
                        "companies": [company],
                    }
                elif company not in existing[key]["companies"]:
                    existing[key]["companies"].append(company)

    if fetched_count == 0 or valid_count == 0:
        raise RuntimeError(f"No usable RSS articles returned (fetched={fetched_count}, valid={valid_count})")
    articles = sorted(existing.values(), key=lambda a: (a["published_at"], a["id"]), reverse=True)
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(articles, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    STATUS_FILE.write_text(json.dumps({
        "last_successful_run": datetime.now(timezone.utc).isoformat(),
        "fetched_this_run": fetched_count,
        "valid_this_run": valid_count,
        "unique_articles_stored": len(articles),
        "collection_method": "Google News RSS search; not an exhaustive media census",
    }, indent=2) + "\n", encoding="utf-8")
    print(f"Success: fetched={fetched_count}, valid={valid_count}, unique_history={len(articles)}")


if __name__ == "__main__":
    main()
