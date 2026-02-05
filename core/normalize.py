"""
Normalization Layer - Filters and cleans discovered items

This layer sits between discovery (RSS) and expansion (fetching).
It applies time-based filters, quality checks, and prepares items
for the expansion stage or direct analysis.
"""

import json
from datetime import datetime, timedelta
from dateutil import parser as date_parser
from pathlib import Path

from core.observability import log


def normalize_items(items, run_id="manual_run", lookback_days=7, min_title_length=10):
    """
    Normalize and filter discovered items.

    Filters:
    - Time window: Only items from last N days (soft check, allows missing dates)
    - Quality: Remove broken URLs, very short titles
    - Duplicates: Remove exact title duplicates (case-insensitive)

    Args:
        items: List of discovered items from RSS
        run_id: Run identifier for logging
        lookback_days: Only keep items from last N days (default: 7 for weekly briefings)
        min_title_length: Minimum title length to keep (default: 10 chars)

    Returns:
        List of normalized items
    """
    cutoff_date = datetime.now() - timedelta(days=lookback_days)
    normalized = []

    filtered_counts = {
        "too_old": 0,
        "no_title": 0,
        "title_too_short": 0,
        "duplicate_title": 0,
        "no_url": 0,
    }

    seen_titles = set()

    log("normalize", "start", {
        "run_id": run_id,
        "input_items": len(items),
        "lookback_days": lookback_days,
        "cutoff_date": cutoff_date.isoformat()
    })

    for item in items:
        # Filter: No URL
        if not item.get("url"):
            filtered_counts["no_url"] += 1
            continue

        # Filter: No title or title too short
        title = item.get("title", "").strip()
        if not title:
            filtered_counts["no_title"] += 1
            continue

        if len(title) < min_title_length:
            filtered_counts["title_too_short"] += 1
            continue

        # Filter: Duplicate title (case-insensitive)
        title_lower = title.lower()
        if title_lower in seen_titles:
            filtered_counts["duplicate_title"] += 1
            log("normalize", "duplicate_title", {
                "run_id": run_id,
                "url": item.get("url"),
                "title": title
            })
            continue

        seen_titles.add(title_lower)

        # Filter: Time window (soft check - allows missing or unparseable dates)
        published = item.get("published", "")
        if published:
            try:
                pub_date = date_parser.parse(published)
                # Make timezone-naive for comparison
                if pub_date.tzinfo:
                    pub_date = pub_date.replace(tzinfo=None)

                if pub_date < cutoff_date:
                    filtered_counts["too_old"] += 1
                    log("normalize", "filtered_old", {
                        "run_id": run_id,
                        "url": item.get("url"),
                        "title": title,
                        "published": published,
                        "age_days": (datetime.now() - pub_date).days
                    })
                    continue
            except (ValueError, TypeError):
                # If date parsing fails, keep the item (soft check)
                pass

        # Item passed all filters
        normalized.append(item)

    log("normalize", "summary", {
        "run_id": run_id,
        "input_items": len(items),
        "output_items": len(normalized),
        "filtered_total": len(items) - len(normalized),
        "filtered_breakdown": filtered_counts,
        "retention_rate": round(len(normalized) / len(items) * 100, 2) if items else 0
    })

    return normalized


def normalize_pipeline(input_path, output_path=None, run_id="manual_run", **kwargs):
    """
    Convenience function to run normalization as a pipeline stage.

    Args:
        input_path: Path to discovered items JSON (e.g., data/raw_sources.json)
        output_path: Path to output normalized items (optional, defaults to same as input)
        run_id: Run identifier
        **kwargs: Additional arguments passed to normalize_items()

    Returns:
        List of normalized items
    """
    input_path = Path(input_path)

    # Load discovered items
    with open(input_path) as f:
        items = json.load(f)

    # Normalize
    normalized = normalize_items(items, run_id=run_id, **kwargs)

    # Save if output path specified
    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w') as f:
            json.dump(normalized, f, indent=2)

        log("normalize", "complete", {
            "run_id": run_id,
            "input_path": str(input_path),
            "output_path": str(output_path),
            "items": len(normalized)
        })

    return normalized
