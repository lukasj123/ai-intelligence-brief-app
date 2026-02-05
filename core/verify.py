import os
from openai import OpenAI
from core.observability import log

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def detect_contestation(claim_text, other_sources, topic_id):
    """
    LLM-assisted binary decision:
    Does any relevant source meaningfully contest this claim?
    """

    if not other_sources:
        return False

    sources_text = "\n".join(f"- {text}" for text in other_sources)

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.0,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an impartial analyst.\n"
                    "Answer ONLY YES or NO."
                )
            },
            {
                "role": "user",
                "content": f"""
Topic: {topic_id}

Claim:
"{claim_text}"

Other sources on the SAME topic:
{sources_text}

Question:
Do any of these sources meaningfully dispute, contradict,
or cast substantive doubt on the claim?
"""
            }
        ],
    )

    answer = response.choices[0].message.content.strip().upper()
    return answer == "YES"


def verify(analysis, raw_data, config):
    """
    Enforce epistemic confidence using:
    - deterministic rules
    - topic-scoped LLM adjudication
    """

    # Build ID lookup dict for efficient access
    items_by_id = {item["id"]: item for item in raw_data}

    # Build topic → source_texts map
    topic_sources = {}

    for item in raw_data:
        topic_sources.setdefault(
            item.get("topic_id", None), []
        ).append(item["content"])

    # Fallback: build from claims if raw sources lack topic_id
    if None in topic_sources:
        topic_sources.clear()
        for claim in analysis.get("claims", []):
            for sid in claim.get("source_ids", []):
                # Use dict lookup with fallback
                item = items_by_id.get(sid)
                if item:
                    topic_sources.setdefault(
                        claim["topic_id"], []
                    ).append(item["content"])

    for idx, claim in enumerate(analysis.get("claims", [])):
        topic_id = claim["topic_id"]
        source_ids = claim.get("source_ids", [])
        source_count = len(source_ids)
        initial_confidence = claim["confidence"]

        log(
            section="verify",
            event_type="claim.start",
            payload={
                "claim_index": idx,
                "topic_id": topic_id,
                "text": claim["text"],
                "initial_confidence": initial_confidence,
                "source_count": source_count
            }
        )

        # Rule 1: corroboration (purely structural)
        if source_count >= 2 and claim["confidence"] == "reported":
            claim["confidence"] = "corroborated"
            log(
                section="verify",
                event_type="claim.corroborated",
                payload={
                    "claim_index": idx,
                    "topic_id": topic_id,
                    "reason": "multiple_sources"
                }
            )

        # Rule 2: contestation (topic-scoped)
        other_sources = topic_sources.get(topic_id, [])

        contested = detect_contestation(
            claim["text"],
            other_sources,
            topic_id
        )

        log(
            section="verify",
            event_type="claim.contestation_check",
            payload={
                "claim_index": idx,
                "topic_id": topic_id,
                "llm_decision": "YES" if contested else "NO",
                "topic_source_count": len(other_sources)
            }
        )

        if contested:
            claim["confidence"] = "contested"
            log(
                section="verify",
                event_type="claim.contested",
                payload={
                    "claim_index": idx,
                    "topic_id": topic_id,
                    "reason": "topic_scoped_dispute_detected"
                }
            )

        log(
            section="verify",
            event_type="claim.final",
            payload={
                "claim_index": idx,
                "topic_id": topic_id,
                "final_confidence": claim["confidence"]
            }
        )

    return analysis
