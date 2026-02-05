import os
import json
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def analyze(raw_data, config):
    """
    Extract factual claims and assign initial topic_ids.
    Topic IDs are provisional and may be normalized later.
    """

    sources_text = "\n\n".join(
        f"[{item['id']}] {item['content']}"
        for item in raw_data
    )

    system_prompt = (
        "You are a careful analytical assistant.\n"
        "Your job is to extract factual claims from news sources.\n"
        "Do not speculate or add facts."
    )

    # Get custom analyzer instructions from environment or use default
    custom_instructions = os.getenv("ANALYZER_INSTRUCTIONS", "")
    custom_section = f"\nCustom Focus:\n{custom_instructions}\n" if custom_instructions else ""

    user_prompt = f"""
Sources:
{sources_text}

Instructions:
- Extract the most important factual claims.
- Base claims strictly on the sources.
- IMPORTANT: For source_ids, use the EXACT IDs from the square brackets (e.g., if you see [gmail:abc123], use "gmail:abc123")
- Assign a short, stable topic_id (snake_case) to each claim.
- Claims about the same real-world topic or event MUST share the same topic_id.
- Topic IDs may be imperfect and will be normalized later.
{custom_section}
Allowed confidence values:
- reported
- inferred
- speculative

Return EXACTLY this JSON schema:
{{
  "claims": [
    {{
      "text": "...",
      "confidence": "reported|inferred|speculative",
      "source_ids": ["actual-source-id-from-brackets"],
      "topic_id": "example_topic_id"
    }}
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
        return json.loads(content)
    except json.JSONDecodeError:
        raise ValueError(f"Invalid JSON from analyze agent:\n{content}")
