from dotenv import load_dotenv
load_dotenv()

import json
from datetime import datetime
from pathlib import Path

from ingest.gmail import fetch_emails
from core.analyze_batched import analyze
from core.normalize_topics import normalize_topics
from core.verify import verify
from core.review import review
from core.format import format_brief
from core.normalize import normalize_items
from core.config import get_lookback_days, get_skip_normalization, load_config
from core.cost_control import check_limits, enforce_limits, print_cost_summary
from deliver.email import deliver_briefing

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"


def run_ingestion(run_id):
    print("=" * 60)
    print("STAGE 1: INGESTION")
    print("=" * 60)

    all_items = []

    print("\n📧 Fetching emails from Gmail...")
    try:
        lookback_days = get_lookback_days()
        gmail_items = fetch_emails(lookback_days=lookback_days, max_results=100, run_id=run_id)
        print(f"✓ Fetched {len(gmail_items)} items from Gmail")
        all_items.extend(gmail_items)
    except Exception as e:
        print(f"⚠️  Gmail ingestion failed: {e}")
        print("Continuing with RSS only...")

    print("\n📡 Fetching RSS feeds...")
    try:
        from ingest.rss import ingest_rss
        ingest_rss(run_id=run_id)

        rss_file = DATA_DIR / "raw_sources.json"
        if rss_file.exists():
            with open(rss_file, 'r') as f:
                rss_items = json.load(f)
            print(f"✓ Fetched {len(rss_items)} items from RSS")
            all_items.extend(rss_items)
        else:
            print("⚠️  RSS data file not found")
    except Exception as e:
        print(f"⚠️  RSS ingestion failed: {e}")

    if not all_items:
        raise ValueError("No items fetched from any source")

    seen_ids = set()
    unique_items = []
    for item in all_items:
        if item['id'] not in seen_ids:
            seen_ids.add(item['id'])
            unique_items.append(item)

    print(f"\n📊 Total items: {len(all_items)} → {len(unique_items)} unique")

    output_file = DATA_DIR / "raw_sources.json"
    with open(output_file, 'w') as f:
        json.dump(unique_items, f, indent=2)

    print(f"💾 Saved to {output_file}")

    return unique_items


def run_analysis(raw_data, config):
    """
    Run analysis pipeline: normalize → analyze → verify → review.

    Returns:
        Reviewed briefing data
    """
    print("\n" + "=" * 60)
    print("STAGE 2: ANALYSIS")
    print("=" * 60)

    if not get_skip_normalization():
        lookback_days = get_lookback_days()
        print(f"\n📊 Normalizing {len(raw_data)} discovered items (lookback: {lookback_days} days)...")
        raw_data = normalize_items(raw_data, run_id="analysis_run", lookback_days=lookback_days)
        print(f"✓ Kept {len(raw_data)} items after normalization")

    cost_check = check_limits(raw_data, run_id="analysis_run")
    print_cost_summary(cost_check)

    raw_data = enforce_limits(raw_data)

    print(f"\n🔍 Analyzing {len(raw_data)} articles...")
    analysis = analyze(raw_data, config)
    print(f"✓ Extracted {len(analysis['claims'])} claims")

    print(f"\n🔗 Normalizing {len(analysis['claims'])} claim topics...")
    analysis = normalize_topics(analysis, config)

    print(f"\n✓ Verifying {len(analysis['claims'])} claims...")
    verified = verify(analysis, raw_data, config)

    print(f"\n📝 Reviewing and synthesizing briefing...")
    reviewed = review(verified, config, raw_sources=raw_data)

    return reviewed, len(analysis['claims']), len(raw_data), raw_data


def run_delivery(briefing_data, claim_count, source_count, raw_sources):
    print("\n" + "=" * 60)
    print("STAGE 3: DELIVERY")
    print("=" * 60)

    config = {
        "claim_count": claim_count,
        "source_count": source_count,
        "show_stats": True,
        "raw_sources": raw_sources  # Pass sources for URL extraction
    }

    # Also print to console
    print("\n" + "=" * 60)
    briefing_text = format_brief(briefing_data, config)
    print(briefing_text)
    print("=" * 60)

    # Send via email
    print("\n📧 Preparing email delivery...")
    try:
        deliver_briefing(briefing_data, config=config)
    except Exception as e:
        print(f"⚠️  Email delivery failed: {e}")
        print("Briefing was printed above for manual review")


def main():
    """
    Run complete pipeline: Ingestion → Analysis → Delivery
    """
    run_id = f"briefing_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    print("\n🧠 AI News Briefing Pipeline")
    print(f"Run ID: {run_id}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    try:
        # Load config from centralized config.yaml
        config = load_config()

        # Stage 1: Ingestion
        raw_data = run_ingestion(run_id)

        # Stage 2: Analysis
        briefing_data, claim_count, source_count, analyzed_sources = run_analysis(raw_data, config)

        # Stage 3: Delivery
        run_delivery(briefing_data, claim_count, source_count, analyzed_sources)

        print("\n" + "=" * 60)
        print("✓ PIPELINE COMPLETE")
        print("=" * 60)
        print(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    except Exception as e:
        print(f"\n❌ Pipeline failed: {e}")
        import traceback
        traceback.print_exc()
        exit(1)


if __name__ == "__main__":
    main()
