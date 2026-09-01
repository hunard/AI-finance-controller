import os
import json
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))


def resolve_unmatched(gateway_record, nearby_bank_candidates):
    """Takes ONE unresolved gateway record and a small list of nearby-ish
    bank candidates (not the whole file - just a handful the deterministic
    layer flagged as 'close but not close enough'). Asks the model to make
    a narrow judgment call: does any of these actually belong to this
    transaction, and how confident is it.

    This is deliberately the ONLY place in the whole pipeline that calls
    an LLM - everything else is rules, because everything else didn't
    need judgment, just calculation."""

    candidates_text = "\n".join(
        f"{i+1}. amount={c['_amount']}, date={c['_date']}, description={c.get('description','')}"
        for i, c in enumerate(nearby_bank_candidates)
    )

    prompt = f"""You are reconciling a payment against bank records.

Gateway transaction: amount={gateway_record['_amount']}, date={gateway_record['_date']}, merchant={gateway_record['merchant']}

Candidate bank records:
{candidates_text}

Does any candidate plausibly correspond to this transaction, accounting for
settlement fees (candidate amount will legitimately be lower than gateway
amount) and possible date drift? Respond ONLY with JSON, no other text:
{{"match_index": <1-based index or null>, "confidence": <0-100>, "reasoning": "<one sentence>"}}"""

    response = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=200,
    )

    raw = response.choices[0].message.content.strip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        # model didn't return clean JSON - treat as unresolved rather
        # than crash or guess
        return {"match_index": None, "confidence": 0, "reasoning": "model returned invalid JSON, treated as no match"}

    return result