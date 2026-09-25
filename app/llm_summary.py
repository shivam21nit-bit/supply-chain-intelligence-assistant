"""LLM-based probable-cause summary — the first real LLM call in this
project, added deliberately once heuristic headline-grouping hit its
ceiling: it can dedupe wire stories, but it can't actually reason about
*why* something is happening or weave trend numbers together with news.

Uses Google's Gemini API (free tier — Flash models, no credit card,
up to 1,000 requests/day) via the `google-genai` SDK.

Critical guardrail: the prompt explicitly tells the model to ground its
answer only in what's given and to say plainly if the evidence doesn't
clearly explain the trend, rather than inventing a confident-sounding
cause. Same honesty standard as every heuristic elsewhere in this
project (spike detection, disruption tagging, rate-limit failures).
"""

import os
import time

from dotenv import load_dotenv
from google import genai
from google.genai import errors as genai_errors

load_dotenv()

# Primary, then a fallback model (verified working for this account) if the
# primary is overloaded — separate models draw from separate free-tier
# capacity pools, so a fallback genuinely improves reliability here rather
# than just retrying the same congested pool twice.
MODEL = "gemini-3.8-flash"
FALLBACK_MODEL = "gemini-flash-lite-latest"

# The SDK already retries transient errors internally, but its own retry
# window is too short for Gemini free-tier "high demand" 503s, which can
# last longer than that. Retry again on top, same backoff-and-retry spirit
# as GDELT's rate-limit handling elsewhere in this project. Kept short
# (a Streamlit script run blocks synchronously — a long unspun wait here
# risks the browser's connection stalling and the page re-rendering oddly).
RETRY_ATTEMPTS = 2
RETRY_BACKOFF_SECONDS = 5


def summarize_cause(subject: str, context_lines: list[str], articles: list[dict]) -> str:
    """subject: what this is about, e.g. "'coffee' demand in US" or
    "Strait of Hormuz (relevant to: Gulf Supplier A, Gulf Supplier B)".
    context_lines: existing computed facts (e.g. the trend summary sentence).
    articles: representative headlines (already deduped by the caller),
    each with title/source/seendate/via.
    """
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not found. Make sure app/.env has a valid key.")

    headline_lines = "\n".join(
        f"- \"{a['title']}\" ({a['source']}, {a['seendate']}, via {a['via']})" for a in articles[:8]
    )
    context_block = "\n".join(context_lines) if context_lines else "(none provided)"
    headline_block = headline_lines if headline_lines else "(none found)"

    prompt = (
        f"Subject: {subject}\n\n"
        f"Known facts (may include real trade statistics and/or real chokepoint transit-volume data):\n{context_block}\n\n"
        f"Recent headlines found:\n{headline_block}\n\n"
        "In 2-4 sentences, explain the likely reason for this and, if relevant, what it "
        "means for the route/supply chain, grounded ONLY in the facts and headlines above.\n\n"
        "Strict rules:\n"
        "- Never state a specific price change, cost figure, or delay/lead-time number "
        "unless that exact figure appears in the facts or headlines above. If none is given, "
        "say plainly that no specific figure is available — do not estimate one yourself.\n"
        "- If a real chokepoint transit-volume figure is given, treat it as the strongest "
        "available signal of the CURRENT situation (it's live-ish data), and mention it.\n"
        "- If an alternate route/source is given as a fact, you may mention it as an option, "
        "including its own transit-volume status if given — but do not suggest an alternate "
        "that isn't explicitly listed in the facts above.\n"
        "- If the facts and headlines don't clearly explain the situation, say so plainly "
        "instead of speculating."
    )

    client = genai.Client(api_key=api_key)
    errors_by_model = {}
    for model in (MODEL, FALLBACK_MODEL):
        try:
            return _call_model(client, model, prompt)
        except RuntimeError as e:
            errors_by_model[model] = str(e)

    detail = "; ".join(f"{m}: {e}" for m, e in errors_by_model.items())
    raise RuntimeError(f"All models overloaded/failed — {detail}")


def _call_model(client: "genai.Client", model: str, prompt: str) -> str:
    last_error = None
    for attempt in range(RETRY_ATTEMPTS):
        try:
            response = client.models.generate_content(model=model, contents=prompt)
        except genai_errors.ServerError as e:
            last_error = f"overloaded ({e.__class__.__name__}): {e}"
            time.sleep(RETRY_BACKOFF_SECONDS)
            continue
        except genai_errors.APIError as e:
            raise RuntimeError(f"API call failed ({e.__class__.__name__}): {e}")

        if not response.text:
            last_error = "returned an empty response"
            time.sleep(RETRY_BACKOFF_SECONDS)
            continue

        return response.text.strip()

    raise RuntimeError(f"{last_error} (gave up after {RETRY_ATTEMPTS} attempts)")
