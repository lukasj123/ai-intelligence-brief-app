import os
from openai import OpenAI
from core.observability import log
from core.config import get_reviewer_focus, get_max_key_points

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def review(verified_analysis, config, raw_sources=None):
    """
    Produce a concise executive briefing from verified claims.
    This step is editorial synthesis only.
    """

    claims = verified_analysis.get("claims", [])

    # Validate that all source_ids referenced in claims exist in raw_sources
    if raw_sources:
        available_source_ids = {source.get('id') for source in raw_sources}
        all_referenced_ids = {sid for claim in claims for sid in claim.get('source_ids', [])}
        missing_ids = all_referenced_ids - available_source_ids

        if missing_ids:
            log(
                section="review",
                event_type="validation_warning",
                payload={
                    "missing_source_count": len(missing_ids),
                    "missing_ids": list(missing_ids)[:10],  # Log first 10
                    "total_sources": len(raw_sources),
                    "message": "Claims reference sources not in raw_sources. This may indicate a pipeline data flow issue."
                }
            )

    source_map = {}
    if raw_sources:
        for source in raw_sources:
            source_id = source.get('id')
            publisher = source.get('publishers', ['Unknown'])[0] if isinstance(source.get('publishers'), list) else source.get('publisher', 'Unknown')
            source_map[source_id] = publisher

    claims_text_parts = []
    claims_with_unknown_sources = []

    for idx, c in enumerate(claims):
        source_names = []
        has_unknown_source = False

        for sid in c.get('source_ids', []):
            if sid in source_map:
                source_names.append(source_map[sid])
            else:
                log(
                    section="review",
                    event_type="missing_source",
                    payload={
                        "source_id": sid,
                        "claim_text": c['text'][:100]
                    }
                )
                source_names.append("Unknown Source")
                has_unknown_source = True

        if has_unknown_source:
            claims_with_unknown_sources.append(idx)

        claims_text_parts.append(
            f"- ({c['confidence']}) {c['text']} [Sources: {', '.join(source_names)}]"
        )

    claims_text = "\n".join(claims_text_parts)

    if claims_with_unknown_sources:
        log(
            section="review",
            event_type="data_quality_issues",
            payload={
                "claims_with_unknown_sources": len(claims_with_unknown_sources),
                "total_claims": len(claims),
                "affected_claim_indices": claims_with_unknown_sources[:10]
            }
        )

    system_prompt = (
        "You are an editorial analyst producing concise executive briefings.\n"
        "You MUST base all statements strictly on the provided claims.\n"
        "Do NOT introduce new facts.\n"
        "Prefer synthesis over enumeration.\n"
        "Be conservative when claims are contested.\n\n"
        "CRITICAL INSTRUCTIONS:\n"
        "- EXCLUDE claims with 'Unknown Source' (indicates data processing issues)\n"
        "- PRIORITIZE the most important and pressing developments\n"
        "- FAVOR claims from diverse sources over claims from a single source\n"
        "- Focus on significance and impact, not just recency"
    )

    custom_focus = get_reviewer_focus()
    custom_section = f"\nCustom Focus:\n{custom_focus}\n" if custom_focus else ""
    max_key_points = get_max_key_points()

    user_prompt = f"""
Verified claims:
{claims_text}

Task:
- Write a short headline.
- Write a 2–3 sentence executive summary.
- Provide up to {max_key_points} key points max.
- Collapse redundant claims.
- If most claims are contested, emphasize uncertainty.

CRITICAL REQUIREMENTS:
1. EXCLUDE any claims with "Unknown Source" - these indicate data quality issues
2. PRIORITIZE claims by importance and impact, not just recency:
   - Major product releases, policy changes, breakthrough research
   - Events with significant real-world implications
   - Novel developments (not incremental updates)
3. DIVERSIFY sources - avoid over-relying on a single source:
   - Prefer claims corroborated by multiple sources
   - If using multiple claims, draw from different publishers when possible
4. Each key point MUST end with source citations in parentheses:
   - Use ONLY publisher names from [Sources: ...], NOT IDs like src_001
   - Example: "OpenAI released GPT-5 (TechCrunch, The Verge)"
   - List unique publisher names only
{custom_section}
Return EXACTLY this JSON format:
{{
  "headline": "...",
  "summary": "...",
  "key_points": [
    "Key point text here (PublisherName1, PublisherName2)"
  ]
}}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.2,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    content = response.choices[0].message.content.strip()

    try:
        import json
        result = json.loads(content)

        key_points = result.get("key_points", [])
        invalid_points = [p for p in key_points if "Unknown Source" in p]

        if invalid_points:
            log(
                section="review",
                event_type="validation_failed",
                payload={
                    "issue": "LLM included Unknown Source claims",
                    "invalid_points_count": len(invalid_points),
                    "invalid_points": invalid_points
                }
            )
            result["key_points"] = [p for p in key_points if "Unknown Source" not in p]
            log(
                section="review",
                event_type="filtered_unknown_sources",
                payload={
                    "filtered_count": len(invalid_points),
                    "remaining_points": len(result["key_points"])
                }
            )

        return result
    except Exception:
        raise ValueError(f"Invalid JSON from review agent:\n{content}")
