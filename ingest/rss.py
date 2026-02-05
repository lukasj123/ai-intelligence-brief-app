import json
import yaml
import feedparser
import requests
import trafilatura
from pathlib import Path

from core.observability import log
from core.ingestion_policy import INGESTION_POLICY


# Paths & constants

BASE_DIR = Path(__file__).resolve().parent
FEEDS_PATH = BASE_DIR.parent / "config" / "rss_feeds.yaml"
OUTPUT_PATH = BASE_DIR.parent / "data" / "raw_sources.json"

MIN_CONTENT_LENGTH = 200


# Load feed config

def load_feeds():
    with open(FEEDS_PATH, "r") as f:
        data = yaml.safe_load(f)
    return data["rss_feeds"]


# Content extraction helpers

def extract_content(entry):
    if "content" in entry and entry.content:
        return entry.content[0].value
    if "summary" in entry:
        return entry.summary
    if "description" in entry:
        return entry.description
    return ""


# Article fetching (for full content extraction)

def fetch_article(url, timeout=20, max_retries=3):
    """
    Fetch full article content from URL using trafilatura.
    Includes retry logic with exponential backoff.

    Args:
        url: Article URL to fetch
        timeout: Request timeout in seconds (default: 20s)
        max_retries: Maximum number of retry attempts (default: 3)

    Returns:
        tuple: (success: bool, content: str, error: str|None)
    """
    import time

    last_error = None

    for attempt in range(max_retries):
        try:
            # Download HTML
            response = requests.get(
                url,
                timeout=timeout,
                headers={
                    'User-Agent': 'Mozilla/5.0 (compatible; AI-News-Bot/1.0)'
                }
            )
            response.raise_for_status()

            # Extract article text using trafilatura
            downloaded = response.text
            extracted = trafilatura.extract(
                downloaded,
                include_comments=False,
                include_tables=False,
                no_fallback=False  # Try fallback extraction if main method fails
            )

            if extracted and len(extracted.strip()) > 100:
                return True, extracted.strip(), None
            else:
                return False, "", "Extraction returned empty or too short"

        except requests.exceptions.Timeout:
            last_error = f"Timeout after {timeout}s"
        except requests.exceptions.RequestException as e:
            last_error = f"Request failed: {str(e)}"
        except Exception as e:
            last_error = f"Unexpected error: {str(e)}"

        if attempt < max_retries - 1:
            backoff = 2 ** attempt
            time.sleep(backoff)

    return False, "", f"{last_error} (after {max_retries} attempts)"


# Main ingestion

def ingest_rss(run_id: str = "manual_run"):
    feeds = load_feeds()

    # Use dict keyed by URL for deduplication
    items_by_url = {}
    total_skipped = 0
    total_items_processed = 0
    dedup_count = 0

    log("ingest", "rss.start", {
        "run_id": run_id,
        "feed_count": len(feeds)
    })

    for publisher, feed_cfg in feeds.items():
        url = feed_cfg["url"]
        source_type = feed_cfg.get("type", "unknown")

        # Tier policy lookup
        policy = INGESTION_POLICY.get(
            source_type,
            INGESTION_POLICY["unknown"]
        )

        feed_items = []
        skipped = {
            "no_content": 0,
            "too_short": 0
        }
        content_lengths = []

        try:
            feed = feedparser.parse(url)
        except Exception as e:
            log("ingest", "rss.feed_error", {
                "run_id": run_id,
                "publisher": publisher,
                "source_type": source_type,
                "error": str(e)
            })
            continue

        for entry in feed.entries:
            raw_content = extract_content(entry)

            if not raw_content:
                skipped["no_content"] += 1
                continue

            content = raw_content.strip()

            # Use tier-specific minimum content length
            min_length = policy.get("min_content_length", MIN_CONTENT_LENGTH)
            if len(content) < min_length:
                skipped["too_short"] += 1
                continue

            article_url = entry.get("link", "")
            if not article_url:
                skipped["no_content"] += 1
                continue

            total_items_processed += 1

            # Check if we've seen this URL before
            if article_url in items_by_url:
                # Merge with existing item
                existing = items_by_url[article_url]

                # Add publisher if not already present
                if publisher not in existing["publishers"]:
                    existing["publishers"].append(publisher)

                # Add source_type if not already present
                if source_type not in existing["source_types"]:
                    existing["source_types"].append(source_type)

                # Use lowest tier (highest priority: tier 1 > tier 2 > ...)
                existing["ingestion_tier"] = min(
                    existing["ingestion_tier"],
                    policy["tier"]
                )

                # Fetch if ANY source wants full article
                existing["fetch_full_article"] = (
                    existing["fetch_full_article"] or policy["fetch_full_article"]
                )

                # Keep longest content
                if len(content) > len(existing["content"]):
                    existing["content"] = content
                    existing["title"] = entry.get("title", existing["title"])
                    existing["published"] = entry.get("published", existing["published"])

                dedup_count += 1

                log("ingest", "rss.duplicate_url", {
                    "run_id": run_id,
                    "url": article_url,
                    "existing_publishers": existing["publishers"][:-1],
                    "new_publisher": publisher,
                    "merged_publishers": existing["publishers"]
                })

            else:
                # New URL - create item
                item = {
                    "id": article_url,  # Use URL as primary key
                    "url": article_url,
                    "publishers": [publisher],  # List for multi-source tracking
                    "source_types": [source_type],  # List for multi-source tracking
                    "ingestion_tier": policy["tier"],
                    "fetch_full_article": policy["fetch_full_article"],
                    "title": entry.get("title", ""),
                    "published": entry.get("published", ""),
                    "content": content,
                    "discovered_at": run_id,
                    "content_source": "rss",  # Track where content came from
                    "fetch_status": None,
                }

                # Fetch full article if policy requires it
                if policy["fetch_full_article"]:
                    success, fetched_content, error = fetch_article(article_url)

                    if success:
                        item["content"] = fetched_content
                        item["content_source"] = "full_article"
                        item["fetch_status"] = "success"
                        log("ingest", "rss.fetch_success", {
                            "run_id": run_id,
                            "url": article_url,
                            "publisher": publisher,
                            "rss_length": len(content),
                            "fetched_length": len(fetched_content),
                            "improvement": len(fetched_content) - len(content)
                        })
                    else:
                        # Fallback to RSS content
                        item["content_source"] = "rss_fallback"
                        item["fetch_status"] = "failed"
                        item["fetch_error"] = error
                        log("ingest", "rss.fetch_failed", {
                            "run_id": run_id,
                            "url": article_url,
                            "publisher": publisher,
                            "error": error,
                            "fallback_length": len(content)
                        })

                items_by_url[article_url] = item
                feed_items.append(item)
                content_lengths.append(len(item["content"]))

        avg_len = int(
            sum(content_lengths) / len(content_lengths)
        ) if content_lengths else 0

        log("ingest", "rss.feed_summary", {
            "run_id": run_id,
            "publisher": publisher,
            "source_type": source_type,
            "ingestion_tier": policy["tier"],
            "fetch_full_article": policy["fetch_full_article"],
            "items_ingested": len(feed_items),
            "items_skipped": sum(skipped.values()),
            "skip_breakdown": skipped,
            "avg_content_length": avg_len
        })

        total_skipped += sum(skipped.values())

    # Convert dict to list for output
    all_items = list(items_by_url.values())

    # Log multi-source articles
    multi_source_articles = [
        item for item in all_items
        if len(item["publishers"]) > 1
    ]

    for item in multi_source_articles:
        log("ingest", "rss.multi_source_article", {
            "run_id": run_id,
            "url": item["url"],
            "title": item["title"],
            "publishers": item["publishers"],
            "source_types": item["source_types"],
            "source_count": len(item["publishers"])
        })

    # Log fetch statistics
    fetch_attempted = sum(1 for item in all_items if item.get("fetch_status") is not None)
    fetch_success = sum(1 for item in all_items if item.get("fetch_status") == "success")
    fetch_failed = sum(1 for item in all_items if item.get("fetch_status") == "failed")

    if fetch_attempted > 0:
        log("ingest", "rss.fetch_summary", {
            "run_id": run_id,
            "fetch_attempted": fetch_attempted,
            "fetch_success": fetch_success,
            "fetch_failed": fetch_failed,
            "fetch_success_rate": round(fetch_success / fetch_attempted * 100, 2)
        })

    log("ingest", "rss.dedup_summary", {
        "run_id": run_id,
        "items_processed": total_items_processed,
        "unique_urls": len(all_items),
        "duplicates_merged": dedup_count,
        "multi_source_articles": len(multi_source_articles),
        "dedup_rate": round(dedup_count / total_items_processed * 100, 2) if total_items_processed > 0 else 0
    })

    log("ingest", "rss.run_summary", {
        "run_id": run_id,
        "total_feeds": len(feeds),
        "total_items": len(all_items),
        "total_skipped": total_skipped,
        "total_items_processed": total_items_processed,
        "duplicates_merged": dedup_count
    })

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(all_items, f, indent=2)

    log("ingest", "rss.complete", {
        "run_id": run_id,
        "output_path": str(OUTPUT_PATH),
        "unique_articles": len(all_items)
    })


# CLI entry

if __name__ == "__main__":
    ingest_rss(run_id="local_test")