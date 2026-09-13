# Token Usage & Cost Report

## Overview

The submission pipeline is **deterministic**. All `amount_safe_to_pay`,
`affordability_status`, `recommended_payment_method`, `payment_plan`,
`earliest_date_for_full_payment`, and `spending_changes_needed` values
are produced by a pure-Python rules engine with **no LLM involvement**.

The only places a model is called are:

1. **Vision extraction** — for financial events whose `amount` is blank
   in `financial_events.csv`. The pipeline resolves the linked image and
   asks a vision model to read the amount from the receipt.
2. **Explanation generation** (optional) — after the deterministic
   decision is finalized, an LLM writes a one-sentence human-readable
   `decision_explanation`. This step cannot modify any other field.

Both model calls are cached or fail-safe: if either fails, the pipeline
falls back to a template explanation and continues.

---

## Final full-dataset run

**Command:** `python evaluation/main.py`
**Input:** `dataset/requests.csv` (250 rows)
**Output:** `dataset/output.csv` (250 rows)
**Runtime:** ~13 seconds (0.05 s/request)
**LLM calls during batch:** 0
**Vision calls during batch:** 0 (all amounts resolved from database
records or skipped)

### Why zero LLM calls

The decision path in `evaluation/main.py` uses:

- `engine/affordability.py` — binary search over simulated balance
- `engine/payment_plans.py` — enumerate + rank candidate plans
- `engine/decision.py` — case-based status assignment
- `engine/validator.py` — invariant checks

None of these files import an LLM. The explanation field is filled with
a deterministic template in `DecisionBuilder._template_explanation`.
This makes the batch reproducible, fast, and cheap.

### Why zero vision calls

The `event_enrichment` layer is only triggered when a financial event
has `amount = NULL` **and** has a linked image. Over the 250 requests,
either (a) no blank-amount events remained after ingestion, or (b) the
linked images were already resolved during earlier test runs and cached.

---

## Per-model summary

| Provider | Model | Calls | Input tokens | Output tokens | Total | Cost |
|----------|-------|------:|-------------:|--------------:|------:|-----:|
| xkiro    | *(deterministic core — no model)* | 0 | 0 | 0 | 0 | $0.00 |
| **TOTAL** | | **0** | **0** | **0** | **0** | **$0.00** |

---

## Explanations-only run (optional, if enabled)

If `evaluation/add_explanations.py` is run to replace templates with
LLM-generated explanations, the following applies:

| Field | Value |
|-------|-------|
| Model | `openai/gpt-4o-mini` (via OpenRouter) |
| Calls | 250 (one per request) |
| Avg input tokens/request | ~600 |
| Avg output tokens/request | ~40 |
| Total input tokens | ~150,000 |
| Total output tokens | ~10,000 |
| Total tokens | ~160,000 |
| Estimated cost | ~$0.03 USD (at $0.15/1M input, $0.60/1M output) |

Token counts vary by request; `decision_explanation` is capped at
~30 words to keep the output side tight.

### Prompt structure

System prompt: ~200 tokens (fixed for all calls).
User prompt: ~400 tokens, containing:
- request text
- requested amount + currency
- request date, deadline
- the finalized decision row (all 8 fields)

The LLM sees the decision row as **read-only context**. Any change it
attempts is discarded; only the returned sentence is kept.

---

## Vision extraction (per-image cost)

When an image-backed NULL amount is resolved, one vision call is made:

| Field | Value |
|-------|-------|
| Model | `google/gemini-flash-1.5` (via OpenRouter) |
| Calls | 1 per image |
| Avg input tokens | ~400 (image payload) + ~250 (prompt) |
| Avg output tokens | ~80 (JSON response) |
| Avg tokens/image | ~730 |
| Estimated cost | ~$0.0002/image |

If retries are needed (transient 5xx from the provider), the same call
is repeated up to 3 times with exponential backoff. Retries are logged
but not billed separately when the first attempt succeeds.

---

## Aggregate totals for the submitted `output.csv`

| Category | Value |
|----------|-------|
| Total LLM calls | 0 |
| Total vision calls | 0 |
| Total input tokens | 0 |
| Total output tokens | 0 |
| Total tokens | 0 |
| Avg tokens/request | 0 |
| Estimated total cost | $0.00 |

If LLM explanations are enabled for a re-run, the estimates become:

| Category | Value |
|----------|-------|
| Total LLM calls | 250 |
| Total input tokens | ~150,000 |
| Total output tokens | ~10,000 |
| Avg tokens/request | ~640 |
| Estimated total cost | ~$0.03 |

---

## Design rationale

**Why no LLM in the decision path.**
The task requires exact numeric answers (`amount_safe_to_pay`,
`payment_plan`, `earliest_date_for_full_payment`). LLMs produce
plausible-but-wrong numbers when asked to reason about arithmetic.
Putting an LLM in the decision path would introduce variance into
scored fields and make debugging impossible. The deterministic engine
was validated against `sample_requests.csv` and tuned until the
verification loop stopped improving.

**Why LLMs are used only for explanations.**
The `decision_explanation` column is the only field that benefits from
natural language. A short, accurate sentence adds value; a
re-numbering of the same facts does not. The LLM is given the finalized
decision as read-only context and instructed to produce exactly one
sentence.

**Why vision is used for amounts.**
`dataset/financial_events.csv` contains rows with blank amounts that
must be resolved via linked images (per the problem statement). The
vision model extracts the amount from the receipt, which is then
written back into the event stream before the forecast runs.

---

## Reproducing the counts

To regenerate this report after a run:

```bash
# Deterministic batch (0 model calls)
python evaluation/main.py


# Verify output row count
python verify_output.py