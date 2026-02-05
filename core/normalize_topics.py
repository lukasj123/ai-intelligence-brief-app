import os
import json
from openai import OpenAI
from core.observability import log

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def normalize_topics(analysis, config):
    """
    Normalize and merge topic_ids produced by analyze().
    Returns analysis with rewritten topic_ids.
    """

    claims = analysis.get("claims", [])
    if not claims:
        return analysis

    # Collect unique topic_ids
    topic_ids = sorted({c["topic_id"] for c in claims})

    log(
        section="topics",
        event_type="normalize.start",
        payload={"topic_ids": topic_ids}
    )

    # If only one topic, nothing to normalize
    if len(topic_ids) == 1:
        return analysis

    system_prompt = (
        "You are organizing topic identifiers.\n"
        "Your job is to merge or rename topic IDs that refer to the same real-world topic.\n"
        "Do NOT invent new topics unless necessary.\n"
        "Be conservative."
    )

    user_prompt = f"""
Topic IDs:
{json.dumps(topic_ids, indent=2)}

Instructions:
- If two or more topic_ids refer to the same real-world topic, map them to ONE canonical topic_id.
- Use short, stable snake_case names.
- If a topic_id is already good, keep it unchanged.
- Do NOT remove topics unless they clearly overlap.

Return EXACTLY this JSON schema:
{{
  "topic_mapping": {{
    "old_topic_id": "canonical_topic_id"
  }}
}}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.0,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    content = response.choices[0].message.content.strip()

    try:
        mapping = json.loads(content)["topic_mapping"]
    except Exception:
        raise ValueError(f"Invalid topic mapping JSON:\n{content}")

    log(
        section="topics",
        event_type="normalize.mapping",
        payload=mapping
    )

    # Apply mapping deterministically
    for claim in claims:
        old = claim["topic_id"]
        if old in mapping:
            claim["topic_id"] = mapping[old]

    log(
        section="topics",
        event_type="normalize.complete",
        payload={
            "final_topic_ids": sorted({c["topic_id"] for c in claims})
        }
    )

    return analysis
