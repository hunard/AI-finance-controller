# AI Finance Controller — Multi-Source Settlement Reconciliation

**Track:** AI Finance Controller (Razorpay AI Buildathon 2026)

## What this does, in one paragraph

Three systems in a payments business almost never agree with each other: what the gateway charged, what actually landed in the bank after fees, and what the merchant's own books recorded. I built an agent that reconciles all three automatically — not just flagging "these don't match," but reconstructing the actual settlement math (gateway fee, GST, platform commission, TDS) to say *exactly* why they don't match. It runs on 60 synthetic transactions, hits 70% accuracy against a known ground truth, and produces an honest list of everything it couldn't resolve, with a reason for each.

## What broke, and how I got out of it

This is the part I'd actually want a reviewer to read first, so here it is early instead of buried at the bottom.

**The bug that taught me the most:** my LLM layer was silently returning zero confidence on every single call. I assumed the model just wasn't finding matches. Turned out `max_tokens=200` was cutting off the response mid-reasoning, before it ever reached the actual JSON answer — `gpt-oss-120b` is a reasoning model, it thinks before it answers, and I hadn't given it room to finish. I only caught it by checking `finish_reason` and seeing `"length"` instead of `"stop"`. Once I raised the token budget, the same calls started returning real, sensible confidence scores.

**The one that made me question my own tolerance values:** my split-detection logic worked perfectly on my one test dataset — found exactly 3 splits, zero false positives. I got suspicious of my own success, tested it across 5 different random seeds, and it fell apart: one seed found zero correct splits and two false ones. I'd tuned a threshold by staring at 3 known answers, which is a real form of overfitting. I fixed it two ways — derived the tolerance mathematically instead of guessing (0.035, from the actual rounding operations in the fee math) and added a second, independent signal (does the bank description plausibly match the merchant name) so a coincidental amount match alone isn't enough. Precision went from 60% to 90% across the same 5 seeds.

**The one where I almost shipped a regression by accident:** I ran a threshold sensitivity sweep, found values that looked better on a simplified test model, applied them to my real pipeline, and accuracy dropped from 65% to 43%. The proxy model I'd swept across didn't actually behave like the real system. I reverted to the validated values and kept the mistake in this README instead of erasing it, because catching your own bad experiment is a more honest signal than pretending it never happened.

**A smaller but real one:** I added a "flag transactions with unusual settlement status" fix, and my accuracy score dropped 22 points overnight. Not a regression — my scoring logic just hadn't been updated to grade the new category correctly, so it was marking correct answers as wrong. A good reminder that the test can be the thing that's broken, not just the code.

## Why I used Groq, specifically — not just "an LLM"

I didn't reach for an LLM everywhere — almost the whole pipeline is deterministic rules, on purpose. The one place I did use one is narrow: a handful of leftover transactions per run that rules genuinely can't resolve, where the question is closer to "does a human judgment call apply here" than "is this a lookup."

For that, I picked Groq over other providers for a specific reason: the task is closer to structured classification than deep reasoning, so speed and cost mattered more to me than squeezing out marginal reasoning quality from a frontier model. Groq's inference is dramatically faster than typical GPU-hosted alternatives, the free tier comfortably covers my volume, and I already had integration patterns from an earlier project, which reduced setup risk under a tight deadline. I was honest with myself that open-weight models can lag proprietary ones on subtle judgment calls — which is exactly why the LLM layer has a confidence floor: anything the model isn't confident about doesn't get forced into a match, it becomes an honest exception instead.

I also deliberately did *not* use an LLM for split detection, even though it looked tempting at first. A hash-based subset-sum search with a mathematically derived tolerance is faster, fully deterministic, and auditable — no reason to pay for a model call when the math itself gives a clean answer.

## The results

| Metric | Value |
|---|---|
| Overall accuracy (single run) | 70.0% |
| Multi-seed mean (N=60, 10 seeds) | 71.8% (range 64.9–80.7%) |
| Scale test mean (N=1000, 5 seeds) | 57.1% (range 54.5–59.8%) |
| Throughput at scale | 4,887–6,613 records/sec |
| Settlement diagnosis precision | 10/13 correctly named the specific cause |
| Split detection precision | 90% (after cross-seed fix, up from 60%) |

The scale-test accuracy drop is a real, traced finding, not noise — at 1,000 records, my fixed-size amount pool and date range cause a 49.6% coincidental collision rate (vs. 10.7% at 60 records), which is a dataset-design limit, not an algorithm one.

## How it's built

Five layers, cheapest and most certain first:

1. **Exact match** — gateway ↔ ledger, identical amount and date
2. **Date-tolerant match** — same idea, allowing for settlement lag
3. **Split detection** — one payment settled as two bank entries, found via hash-based two-sum, confirmed with a second vendor-similarity signal
4. **Optimal settlement match** — gateway ↔ bank, using the Hungarian algorithm to find the single best overall pairing across every transaction at once, not just a greedy first-match
5. **LLM resolver** — genuine leftovers only, cached so repeated runs give identical results

Order matters more than it looks: split detection has to run *before* the 1:1 optimal matcher, on the full data, not leftovers — I found out the hard way that individual split-transaction bank rows get greedily claimed by unrelated transactions if the 1:1 matcher runs first.
## Technical design decisions

**Why the Hungarian algorithm over greedy matching, formally stated:** the gateway-to-bank matching problem is an assignment problem — given a cost matrix where `cost[i][j]` is the settlement gap between gateway transaction *i* and bank record *j*, find the assignment minimizing total cost across *all* pairs simultaneously. A greedy first-match approach processes records in arbitrary order and locally optimizes each decision independently, which is provably suboptimal whenever two transactions compete for the same candidate — exactly what happened here: a genuine ₹62.07 GST-miscalculation gap got skipped because a smaller, unrelated ₹58 gap claimed the same bank record first, since it was processed earlier. `scipy.optimize.linear_sum_assignment` solves this in O(n³) via the Hungarian algorithm, which is tractable at this scale (60–1000 records) and guarantees the assignment isn't locally trapped by processing order. Measured effect: 63.2% → 64.9% accuracy on the same dataset, with the specific misdiagnosis case corrected.

**Why split detection needed a different algorithm entirely, not a bipartite-matching tweak:** the Hungarian algorithm assumes a strict one-to-one mapping. Split transactions are structurally one-to-many (one gateway record, two bank entries) — no reweighting of the cost matrix can represent that relationship, because the algorithm's underlying assumption doesn't fit the problem shape. This needed a genuinely different technique: a 2-SUM search over the leftover bank pool. The naive version is O(n²) (`itertools.combinations` over every pair); I reduced it to O(n) via a bucketed hash lookup — since the match tolerance is only ±0.035, the complement of any candidate amount can only fall into one of 3 adjacent 1-cent buckets, so each candidate needs 3 constant-time dictionary lookups instead of an O(n) linear scan of a sorted list. Verified: identical results to the O(n²) version, ~30% faster even at n=57; the gap widens combinatorially at production volume (500,000 comparisons at n=1000 vs. ~1,000 with bucketing).

**Deriving the split tolerance from the actual computation, not from the test data:** `expected_settlement()` performs 4 independent `round(x, 2)` operations (gateway fee, GST-on-fee, commission, TDS) plus a final rounding of the net — 5 compounding roundings, each with a worst-case error of ±0.005 (half a paisa). Summing worst cases gives a principled upper bound of 0.035, not a number reverse-engineered from matching 3 known examples. I initially *did* reverse-engineer it (found 0.03 empirically, which happened to be close), then validated the derived value across 5 independently-seeded datasets and found amount-matching alone was still unreliable (40% recall, 60% precision) — coincidental pair-sums are common when the underlying amount pool clusters around ~15 common price points. Adding a second, independent signal (Levenshtein-based vendor description similarity via `rapidfuzz`, requiring both bank rows to plausibly reference the same merchant) resolved most of the false positives (60% recall, 90% precision) without loosening the numeric tolerance at all — the fix was adding an orthogonal signal, not tuning a threshold further.

**Why bucketed hashing works correctly here specifically:** bucketing by rounded amount is only safe because the tolerance (0.035) is smaller than the bucket width (0.01 × 3 = 0.03 coverage, extended to fully cover 0.035 by symmetric ±1-cent buckets around the exact complement). A larger tolerance relative to bucket granularity would require either finer buckets or a range-query structure (e.g., a sorted array with binary search) instead of exact-key hashing — a real constraint I checked explicitly rather than assumed.

**Why status-aware filtering had to happen at the report layer, not the matching layer:** `expected_settlement()` has no way to know a transaction failed or was refunded — it's a pure function of amount and payment method, by design, so it stays independently testable. Injecting a status check into it would couple settlement math to transaction lifecycle state, two genuinely separate concerns. The correct layer for that gate is `build_final_report()`, which already owns the decision of what verdict a transaction receives — keeping the boundary there means `expected_settlement()` and `diagnose_settlement_gap()` remain pure, unit-testable functions with no hidden state dependency.

**A negative result I kept instead of hiding:** cross-validating my originally-hand-tuned thresholds (date tolerance, settlement match tolerance) via a 5-seed sweep suggested tighter values would generalize better. Applying them to the *real* pipeline dropped accuracy from 65.0% to 43.3% — the sweep ran against a simplified proxy reimplementation (built for speed, not fidelity) that didn't actually represent the production matcher's behavior closely enough for its conclusions to transfer. I reverted to the values validated end-to-end on the real system. This is worth stating explicitly: a systematic validation methodology is only as trustworthy as the fidelity of what it's validating against, and I'd rather show I caught that gap than pretend the sweep worked cleanly.

## Real-world implementation — how I'd actually deploy this

The matching engine itself wouldn't change at all. What would change:

- **Data sources** — `run_daily.py`'s `fetch_latest_sources()` currently reads local CSVs; in production it would call Razorpay's Settlement API, a bank API or account aggregator, and the merchant's accounting software API instead.
- **Fee rates** — currently sit in `config.json` as placeholders; in production they'd be pulled per-merchant from Razorpay's account config via API, since real merchants negotiate individual pricing.
- **Scheduling** — this would run as a daily job right after each settlement cycle clears (T+2 typically), not triggered by hand.
- **Output routing** — exceptions currently write to a local JSON file; in production they'd go to a finance team's dashboard or a Slack/email alert, sorted by what actually needs a human's attention first.

Who'd actually use it: a merchant running Razorpay Route (splitting payments across multiple sellers) verifying their settlements are mathematically correct before month-end, or Razorpay's own internal finance-ops team auditing that the settlement engine is paying out the right amount to every seller — catching a systemic fee-calculation bug before it compounds across thousands of transactions.

## Known limitations, stated plainly

- Split detection only handles two-way splits.
- The LLM confidence threshold (65) wasn't cross-seed validated the way my other thresholds were — a real, stated gap, not an oversight.
- Fee/commission rates are realistic placeholders from public documentation, not live Razorpay merchant pricing.

## Setup

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python data\generate_synthetic.py
python run_daily.py
python tests\test_deterministic.py
```

Needs a `.env` file: `GROQ_API_KEY=your_key` (free tier, no card required).

## What's in this repo

```
data/generate_synthetic.py   — builds the synthetic dataset
engine/deterministic.py      — every matching layer (exact, date-tolerant, splits, optimal)
engine/report.py             — combines everything into one verdict per transaction
engine/score.py              — grades the result against ground truth
engine/llm_resolver.py       — the one LLM call in the whole pipeline, cached
config.json                  — fee rates and matching thresholds
run_daily.py                 — runs the whole pipeline as one command
tests/test_deterministic.py  — regression tests for bugs I've already hit once
```s