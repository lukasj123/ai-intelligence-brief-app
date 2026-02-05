#!/usr/bin/env python3
"""
Test script for LLM-verified publisher extraction with caching.
"""

import sys
from pathlib import Path

# Add parent directory to path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from ingest.gmail import (
    extract_email_from_header,
    try_regex_extraction,
    verify_publisher_with_llm,
    extract_publisher_name,
    lookup_publisher_cache,
    load_publisher_cache
)


def test_email_extraction():
    """Test email address extraction from various From header formats."""
    print("\n" + "=" * 60)
    print("TEST 1: Email Extraction")
    print("=" * 60)

    test_cases = [
        ("AI Weekly <newsletter@aiweekly.com>", "newsletter@aiweekly.com"),
        ("newsletter@example.com", "newsletter@example.com"),
        ('"ImportAI" <jack@jack-clark.net>', "jack@jack-clark.net"),
        ("no-reply@substack.com", "no-reply@substack.com"),
    ]

    for from_header, expected in test_cases:
        result = extract_email_from_header(from_header)
        status = "✓" if result == expected else "✗"
        print(f"{status} {from_header}")
        print(f"  → {result} (expected: {expected})")


def test_regex_extraction():
    """Test regex-based publisher name extraction."""
    print("\n" + "=" * 60)
    print("TEST 2: Regex Extraction")
    print("=" * 60)

    test_cases = [
        {
            "from": "AI Weekly <newsletter@aiweekly.com>",
            "subject": "AI Weekly #245: Latest in AI",
            "list_id": None,
            "expected_contains": "AI Weekly"
        },
        {
            "from": "newsletter.subscriptions.email@gmail.com",
            "subject": "Your Daily Digest",
            "list_id": None,
            "expected_contains": "Newsletter"
        },
        {
            "from": "ImportAI <jack@jack-clark.net>",
            "subject": "ImportAI 345",
            "list_id": None,
            "expected_contains": "ImportAI"
        },
    ]

    for test in test_cases:
        result = try_regex_extraction(
            from_header=test["from"],
            subject=test["subject"],
            list_id=test["list_id"]
        )
        status = "✓" if test["expected_contains"].lower() in result.lower() else "~"
        print(f"{status} {test['from']}")
        print(f"  → {result}")


def test_llm_verification():
    """Test LLM verification of regex extractions."""
    print("\n" + "=" * 60)
    print("TEST 3: LLM Verification")
    print("=" * 60)

    test_cases = [
        {
            "regex_guess": "Newsletter Subscriptions Email",
            "from": "newsletter.subscriptions.email@gmail.com",
            "subject": "OpenAI Developer News - January 2026"
        },
        {
            "regex_guess": "AI Weekly",
            "from": "AI Weekly <newsletter@aiweekly.com>",
            "subject": "AI Weekly #245: GPT-5 Released"
        },
    ]

    for test in test_cases:
        print(f"\nRegex guess: '{test['regex_guess']}'")
        print(f"From: {test['from']}")
        print(f"Subject: {test['subject']}")

        verified = verify_publisher_with_llm(
            regex_guess=test["regex_guess"],
            from_header=test["from"],
            subject=test["subject"]
        )

        print(f"LLM verified: '{verified}'")

        # Check if it improved or kept the same
        if verified != test["regex_guess"]:
            print(f"  → LLM CORRECTED the extraction")
        else:
            print(f"  → LLM CONFIRMED regex result")


def test_full_extraction_with_cache():
    """Test full extraction pipeline with caching."""
    print("\n" + "=" * 60)
    print("TEST 4: Full Extraction with Caching")
    print("=" * 60)

    # Use a unique test email to avoid conflicts with real cache
    test_email = "test-newsletter-123@example.com"
    from_header = f"Test Newsletter <{test_email}>"
    subject = "Weekly AI Update"

    print(f"First extraction (should call LLM):")
    result1 = extract_publisher_name(from_header, subject=subject, force_reverify=True)
    print(f"  → {result1}")

    print(f"\nSecond extraction (should use cache):")
    result2 = extract_publisher_name(from_header, subject=subject)
    print(f"  → {result2}")

    # Verify they match
    if result1 == result2:
        print(f"✓ Cache working correctly - both returned: {result1}")
    else:
        print(f"✗ Cache issue - results differ: {result1} vs {result2}")

    # Check cache file
    cached_value = lookup_publisher_cache(test_email)
    if cached_value:
        print(f"✓ Found in cache: {test_email} → {cached_value}")
    else:
        print(f"✗ Not found in cache")


def show_cache_stats():
    """Display cache statistics."""
    print("\n" + "=" * 60)
    print("CACHE STATISTICS")
    print("=" * 60)

    cache = load_publisher_cache()
    print(f"Total cached publishers: {len(cache)}")

    if cache:
        print("\nCached mappings:")
        for email, publisher in sorted(cache.items())[:10]:  # Show first 10
            print(f"  {email[:40]:40} → {publisher}")
        if len(cache) > 10:
            print(f"  ... and {len(cache) - 10} more")


def main():
    """Run all tests."""
    print("=" * 60)
    print("PUBLISHER EXTRACTION TEST SUITE")
    print("=" * 60)

    try:
        test_email_extraction()
        test_regex_extraction()
        test_llm_verification()
        test_full_extraction_with_cache()
        show_cache_stats()

        print("\n" + "=" * 60)
        print("✓ ALL TESTS COMPLETE")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
