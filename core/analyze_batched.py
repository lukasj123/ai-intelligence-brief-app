import os
import json
from openai import OpenAI
from core.config import get_analyzer_instructions

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

BATCH_SIZE = 50


def estimate_token_count(text):
    return len(text) // 4


def analyze_batch(batch_data, config, batch_num=1, total_batches=1):
    sources_text = "\n\n".join(
        f"[{item['id']}] {item['content'][:5000]}"
        for item in batch_data
    )

    system_prompt = (
        "You are a careful analytical assistant.\n"
        "Your job is to extract factual claims from news sources.\n"
        "Do not speculate or add facts."
    )

    custom_instructions = get_analyzer_instructions()
    custom_section = f"\nCustom Focus:\n{custom_instructions}\n" if custom_instructions else ""

    user_prompt = f"""
Sources (Batch {batch_num}/{total_batches}):
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

    print(f"   Analyzing batch {batch_num}/{total_batches} ({len(batch_data)} articles)...")

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
        print(f"   Warning: Batch {batch_num} returned invalid JSON, skipping")
        return {"claims": []}


def analyze(raw_data, config):
    """
    Extract factual claims with automatic batching for large datasets.

    Splits data into batches to avoid OpenAI rate limits (429 errors).
    """
    total_items = len(raw_data)

    # Calculate number of batches needed
    num_batches = (total_items + BATCH_SIZE - 1) // BATCH_SIZE

    if num_batches == 1:
        print(f"🔍 Analyzing {total_items} articles (single batch)...")
    else:
        print(f"🔍 Analyzing {total_items} articles ({num_batches} batches of ~{BATCH_SIZE})...")

    all_claims = []

    # Process each batch
    for i in range(num_batches):
        start_idx = i * BATCH_SIZE
        end_idx = min((i + 1) * BATCH_SIZE, total_items)
        batch = raw_data[start_idx:end_idx]

        batch_result = analyze_batch(batch, config, batch_num=i+1, total_batches=num_batches)
        all_claims.extend(batch_result.get("claims", []))

    print(f"✓ Extracted {len(all_claims)} total claims from {num_batches} batch(es)")

    return {"claims": all_claims}
