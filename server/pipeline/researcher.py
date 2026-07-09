import json
import logging
import os
import time

from openai import OpenAI, OpenAIError

from .schema import RESEARCH_SCHEMA

log = logging.getLogger("toolkit_scout")

MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

PRICE_PER_1M_INPUT = 0.15
PRICE_PER_1M_OUTPUT = 0.60
PRICE_PER_SEARCH_CALL = 0.01

SYSTEM_PROMPT = """\
You are a research analyst at Composio, a company that turns SaaS apps into
tools AI agents can call (MCP servers / agent toolkits). For the given app,
research its PUBLIC developer documentation and pricing pages, then report:

- category, one-line description
- authentication methods its public API supports
- access model: can a developer get API access self-serve for free, via a
  trial, only on a paid plan, or only through a partnership/approval process?
- API surface: REST/GraphQL/etc., roughly how broad, anything notable
- whether an official or well-known MCP server already exists for it
- buildability verdict: could Composio build an agent toolkit for it today
  ("ready_today"), with some workaround ("possible_with_workaround"),
  or is it blocked ("blocked")? Name the blocker if any.

Rules:
- Prefer official docs (developer.x.com, docs.x.com, api.x.com etc.) as evidence.
- evidence_url MUST be a real URL you actually consulted, ideally the API/auth docs.
- Put everything you found, including uncertainty, in raw_notes BEFORE deciding
  the structured fields. Be honest with the confidence field.
- If you cannot find reliable information, use "unclear"/"unknown" values and
  low confidence rather than guessing.
"""

_composio = None


def _get_composio():
    global _composio
    if _composio is None:
        from composio import Composio

        _composio = Composio()
    return _composio


def _build_user_prompt(app_name: str, hint_url: str | None) -> str:
    prompt = f"Research the app: {app_name}"
    if hint_url:
        prompt += f"\nHint URL (likely its homepage or docs): {hint_url}"
    return prompt


def _run_with_composio(client: OpenAI, app_name: str, hint_url: str | None
                       ) -> tuple[dict, dict]:
    composio = _get_composio()
    search_calls = 0
    evidence_chunks = []
    for query in (f"{app_name} API authentication methods developer docs",
                  f"{app_name} API pricing self-serve access MCP server"):
        result = composio.tools.execute(
            "COMPOSIO_SEARCH_WEB",
            arguments={"query": query},
            user_id="toolkit-scout",
            version="latest:base",
        )
        search_calls += 1
        evidence_chunks.append(json.dumps(result, default=str)[:6000])

    prompt = (
        _build_user_prompt(app_name, hint_url)
        + "\n\nWEB SEARCH RESULTS (via Composio composio_search):\n"
        + "\n---\n".join(evidence_chunks)
    )
    resp = client.responses.create(
        model=MODEL,
        instructions=SYSTEM_PROMPT,
        input=prompt,
        text={"format": {"type": "json_schema", **RESEARCH_SCHEMA}},
        max_output_tokens=2000,
    )
    usage = {"input_tokens": resp.usage.input_tokens,
             "output_tokens": resp.usage.output_tokens,
             "search_calls": search_calls}
    return json.loads(resp.output_text), usage


def _run_with_openai_search(client: OpenAI, app_name: str, hint_url: str | None,
                            force_search: bool = True) -> tuple[dict, dict]:
    kwargs = {
        "model": MODEL,
        "instructions": SYSTEM_PROMPT,
        "input": _build_user_prompt(app_name, hint_url),
        "tools": [{"type": "web_search"}],
        "text": {"format": {"type": "json_schema", **RESEARCH_SCHEMA}},
        "max_output_tokens": 2000,
    }
    if force_search:
        kwargs["tool_choice"] = {"type": "web_search"}
    resp = client.responses.create(**kwargs)
    search_calls = sum(
        1 for item in resp.output
        if getattr(item, "type", "") == "web_search_call")
    usage = {"input_tokens": resp.usage.input_tokens,
             "output_tokens": resp.usage.output_tokens,
             "search_calls": search_calls}
    return json.loads(resp.output_text), usage


def research_app(client: OpenAI, app_name: str, hint_url: str | None = None,
                 max_retries: int = 2) -> dict:
    started = time.time()
    base = {"app_name": app_name, "hint_url": hint_url}
    use_composio = bool(os.environ.get("COMPOSIO_API_KEY"))
    force_search = True

    last_error = None
    for attempt in range(max_retries + 1):
        try:
            if use_composio:
                try:
                    data, usage = _run_with_composio(client, app_name, hint_url)
                    backend = "composio_search"
                except Exception as e:
                    log.warning("composio backend failed (%s), falling back to openai web_search", e)
                    use_composio = False
                    continue
            else:
                data, usage = _run_with_openai_search(
                    client, app_name, hint_url, force_search)
                backend = "openai_web_search"

            cost_usd = (
                usage["input_tokens"] / 1e6 * PRICE_PER_1M_INPUT
                + usage["output_tokens"] / 1e6 * PRICE_PER_1M_OUTPUT
                + usage["search_calls"] * PRICE_PER_SEARCH_CALL
            )
            record = {
                **base,
                "status": "ok",
                "data": data,
                "cost": {
                    "input_tokens": usage["input_tokens"],
                    "output_tokens": usage["output_tokens"],
                    "web_search_calls": usage["search_calls"],
                    "estimated_usd": round(cost_usd, 5),
                },
                "elapsed_s": round(time.time() - started, 1),
                "model": MODEL,
                "search_backend": backend,
            }
            log.info("ok %-20s $%.4f (%d searches via %s, %.1fs)",
                     app_name, cost_usd, usage["search_calls"], backend,
                     record["elapsed_s"])
            return record

        except json.JSONDecodeError as e:
            last_error = f"model returned invalid JSON: {e}"
        except OpenAIError as e:
            last_error = f"OpenAI API error: {e}"
            if force_search and "tool_choice" in str(e):
                force_search = False
        except Exception as e:
            last_error = f"unexpected error: {type(e).__name__}: {e}"
        if attempt < max_retries:
            time.sleep(2 * (attempt + 1))

    log.warning("FAILED %-20s %s", app_name, last_error)
    return {
        **base,
        "status": "research_failed",
        "reason": last_error,
        "cost": {"input_tokens": 0, "output_tokens": 0,
                 "web_search_calls": 0, "estimated_usd": 0.0},
        "elapsed_s": round(time.time() - started, 1),
        "model": MODEL,
    }
