from dotenv import load_dotenv
load_dotenv()

import yaml
import json
import os

from core.analyze_batched import analyze  # Use batched version for large datasets
from core.normalize_topics import normalize_topics
from core.verify import verify
from core.format import format_brief
from core.review import review
from core.normalize import normalize_items
from core.config import get_lookback_days
from core.cost_control import check_limits, enforce_limits, print_cost_summary

def main():
    with open("config/example.yaml") as f:
        config = yaml.safe_load(f)

    with open("data/raw_sources.json") as f:
        raw_data = json.load(f)

    # Optional: Normalize ingested data (filter by time/quality)
    # Set SKIP_NORMALIZATION=1 to use all discovered items
    if not os.getenv("SKIP_NORMALIZATION"):
        # Use centralized lookback period (env var overrides if set)
        lookback_days = int(os.getenv("LOOKBACK_DAYS")) if os.getenv("LOOKBACK_DAYS") else get_lookback_days()
        print(f"Normalizing {len(raw_data)} discovered items (lookback: {lookback_days} days)...")
        raw_data = normalize_items(raw_data, run_id="analysis_run", lookback_days=lookback_days)
        print(f"✓ Kept {len(raw_data)} items after normalization\n")

    # Cost control check
    cost_check = check_limits(raw_data, run_id="analysis_run")
    print_cost_summary(cost_check)

    # Enforce limits (truncate if needed)
    raw_data = enforce_limits(raw_data)

    # Analysis pipeline
    print(f"Analyzing {len(raw_data)} articles...")
    analysis = analyze(raw_data, config)

    print(f"🔗 Normalizing {len(analysis['claims'])} claim topics...")
    analysis = normalize_topics(analysis, config)

    print(f"✓ Verifying {len(analysis['claims'])} claims...")
    verified = verify(analysis, raw_data, config)

    print(f"Reviewing and synthesizing briefing...")
    reviewed = review(verified, config, raw_sources=raw_data)

    print(f"Formatting final briefing...\n")
    # Add raw_data to config for source links
    config["raw_sources"] = raw_data
    briefing = format_brief(reviewed, config)

    print("=" * 60)
    print(briefing)
    print("=" * 60)


if __name__ == "__main__":
    main()