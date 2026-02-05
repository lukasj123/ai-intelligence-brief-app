# Defines ingestion behavior by source type
# Maps directly to "type" field in config/rss_feeds.yaml

INGESTION_POLICY = {
    #TIER 1: Professional journalism (fetch full articles)
    "news": {
        "tier": 1,
        "fetch_full_article": True,
        "min_content_length": 0,
        "notes": "Professional journalism - fetch full articles (FT, Bloomberg, StatNews)"
    },

    #TIER 2: High-quality analysis and corporate research
    "corporate_research": {
        "tier": 2,
        "fetch_full_article": False,
        "min_content_length": 200,
        "notes": "Corporate research (Microsoft, Amazon) - RSS already rich"
    },

    "analysis_newsletter": {
        "tier": 2,
        "fetch_full_article": False,
        "min_content_length": 200,
        "notes": "Expert analysis (SemiAnalysis, Stratechery) - RSS already rich"
    },

    #TIER 3: Frontier labs and vendor content (marketing-heavy)
    "frontier_lab": {
        "tier": 3,
        "fetch_full_article": False,
        "min_content_length": 100,
        "notes": "Frontier labs (OpenAI, Anthropic, DeepMind) - RSS has short snippets (~230-260 chars), lowered threshold to reduce 86% skip rate"
    },

    "vendor_blog": {
        "tier": 3,
        "fetch_full_article": False,
        "min_content_length": 100,
        "notes": "Vendor blogs (NVIDIA) - lowered threshold to match frontier_lab behavior"
    },

    #TIER 4: Policy orgs and press releases
    "policy_org": {
        "tier": 4,
        "fetch_full_article": False,
        "min_content_length": 200,
        "notes": "Think tanks, NGOs (EFF, Brookings, Aspen) - RSS already rich (8K-25K chars), 0% skip rate"
    },

    "press_release": {
        "tier": 4,
        "fetch_full_article": False,
        "min_content_length": 100,
        "notes": "Government agencies (White House, FDA, FTC, NIST) - short releases (~220-250 chars), lowered threshold to reduce 40-95% skip rate"
    },

    #TIER 5: Special cases (need custom handling)
    "research_journal": {
        "tier": 5,
        "fetch_full_article": False,
        "min_content_length": 200,
        "notes": "Academic journals (Nature, JAMA) - abstracts only, may need DOI lookup"
    },

    "community_blog": {
        "tier": 5,
        "fetch_full_article": True,
        "min_content_length": 0,
        "notes": "Community blogs (HuggingFace, PyTorch) - often no content in RSS"
    },

    # Fallback for unknown types
    "unknown": {
        "tier": 5,
        "fetch_full_article": False,
        "min_content_length": 200,
        "notes": "Unknown source type - default to low priority"
    }
}
