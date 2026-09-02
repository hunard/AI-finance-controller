import os
import json
import hashlib
from pathlib import Path
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

CACHE_PATH = Path("llm_cache.json")


def resolve_unmatched(gateway_record, nearby_bank_candidates):
    """Takes ONE unresolved gateway record and a small list of nearby-ish
    bank candidates. Asks the model to make a narrow judgment call: does
    any of these actually belong to this transaction, and how confident
    is it.

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
        max_tokens=1024,
    )

    raw = response.choices[0].message.content.strip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        return {"match_index": None, "confidence": 0, "reasoning": "model returned invalid JSON, treated as no match"}

    return result


def _cache_key(gateway_record, candidates):
    candidate_fingerprint = "|".join(
        f"{c['_amount']}:{c['_date']}" for c in candidates
    )
    raw = f"{gateway_record['payment_id']}:{candidate_fingerprint}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _load_cache():
    if CACHE_PATH.exists():
        with open(CACHE_PATH) as f:
            return json.load(f)
    return {}


def _save_cache(cache):
    with open(CACHE_PATH, "w") as f:
        json.dump(cache, f, indent=2)


def cached_resolve(gateway_record, candidates):
    """Checks the cache first, only calls the real (expensive,
    non-deterministic) LLM if this exact question hasn't been asked
    before - guarantees repeated runs on the same data give identical
    results."""

    cache = _load_cache()
    key = _cache_key(gateway_record, candidates)

    if key in cache:
        return cache[key]

    result = resolve_unmatched(gateway_record, candidates)
    cache[key] = result
    _save_cache(cache)
    return result


def apply_llm_layer(report, bank_leftover_gateway, bank_leftover_bank,
                     date_window_days=7, confidence_threshold=65):
    """Takes whatever the earlier layers couldn't resolve, and gives the
    LLM one last narrow shot at it - only on genuine leftovers."""

    leftover_by_payment_id = {g["payment_id"]: g for g in bank_leftover_gateway}

    for entry in report:
        pid = entry["payment_id"]
        if entry["verdict"] not in ("bank_missing", "unresolved"):
            continue
        if pid not in leftover_by_payment_id:
            continue

        gateway_record = leftover_by_payment_id[pid]

        candidates = [
            b for b in bank_leftover_bank
            if abs((b["_date"] - gateway_record["_date"]).days) <= date_window_days
        ]

        if not candidates:
            entry["llm_checked"] = True
            entry["llm_result"] = "no nearby candidates to consider"
            continue

        candidates = candidates[:5]

        result = cached_resolve(gateway_record, candidates)
        entry["llm_checked"] = True

        if result.get("match_index") and result.get("confidence", 0) >= confidence_threshold:
            entry["verdict"] = "llm_resolved"
            entry["llm_confidence"] = result["confidence"]
            entry["llm_reasoning"] = result["reasoning"]
        else:
            entry["llm_result"] = f"no confident match (best guess confidence: {result.get('confidence', 0)})"

    return report