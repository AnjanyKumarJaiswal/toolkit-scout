import json
import logging
import re

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from openai import OpenAI

from .researcher import MODEL
from .review import load_decisions, save_decisions, compute_accuracy
from .runner import SERVER_DIR, load_results, save_results
from .schema import ACCESS_MODELS, AUTH_METHODS, CATEGORIES, VERDICTS

log = logging.getLogger("toolkit_scout")

MAX_PAGE_CHARS = 9000

FIELD_PROMPTS = {
    "category": f"the product category — value MUST be exactly one of {CATEGORIES}",
    "auth_methods": f"the authentication methods the public API supports — value MUST be a list drawn from {AUTH_METHODS}",
    "access_model": f"the API access model — value MUST be exactly one of {ACCESS_MODELS}",
    "api_surface": 'the API surface — value MUST be an object {"api_types": [...], "breadth": "narrow|moderate|broad|unknown", "notes": "..."}',
    "has_existing_mcp": 'whether an official or well-known MCP server exists — value MUST be an object {"exists": bool, "note": "..."}',
    "buildability_verdict": f"whether an agent toolkit could be built — value MUST be exactly one of {VERDICTS}",
}


def _valid_value(field: str, value) -> bool:
    if field == "category":
        return value in CATEGORIES
    if field == "auth_methods":
        return isinstance(value, list) and value and all(v in AUTH_METHODS for v in value)
    if field == "access_model":
        return value in ACCESS_MODELS
    if field == "buildability_verdict":
        return value in VERDICTS
    if field == "api_surface":
        return isinstance(value, dict) and "api_types" in value and "breadth" in value
    if field == "has_existing_mcp":
        return isinstance(value, dict) and isinstance(value.get("exists"), bool)
    return False


def fetch_page_text(url: str) -> str | None:
    try:
        resp = requests.get(url, timeout=20, headers={
            "User-Agent": "Mozilla/5.0 (toolkit-scout verification bot)"})
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        return re.sub(r"\s+", " ", soup.get_text(" ")).strip()[:MAX_PAGE_CHARS]
    except requests.RequestException:
        return None


def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def reextract_field(client: OpenAI, app_name: str, field: str, page_text: str) -> dict | None:
    prompt = (
        f"Below is the text of a documentation page for {app_name}.\n"
        f"Determine {FIELD_PROMPTS[field]}, using ONLY this page text.\n"
        f'Return JSON: {{"value": <the corrected value for field "{field}">, '
        f'"quote": <an EXACT substring copied verbatim from the page that supports it>}}.\n'
        f'If the page does not contain enough information, return {{"value": null, "quote": null}}.\n\n'
        f"PAGE TEXT:\n{page_text}"
    )
    try:
        resp = client.responses.create(
            model=MODEL,
            input=prompt,
            text={"format": {"type": "json_object"}},
            max_output_tokens=500,
        )
        return json.loads(resp.output_text)
    except Exception as e:
        log.warning("re-extract failed for %s.%s: %s", app_name, field, e)
        return None


def run_pass2() -> dict:
    load_dotenv(SERVER_DIR / ".env")
    client = OpenAI()

    decisions = load_decisions()
    round1 = decisions.get("round1", {})
    round2 = decisions.setdefault("round2", {})
    results = load_results()

    targets = [
        (app, field)
        for app, fields in round1.items()
        for field, verdict in fields.items()
        if verdict == "incorrect"
    ]
    if not targets:
        print("no fields marked incorrect in round 1 — nothing to do")
        return decisions

    for app, field in targets:
        record = results["records"].get(app)
        if not record or record["status"] != "ok":
            continue
        if field == "evidence_url":
            round2.setdefault(app, {})[field] = "unsure"
            print(f"{app}.{field}: skipped (evidence_url must be re-judged by hand)")
            continue

        url = record["data"]["evidence_url"] or record.get("hint_url")
        page_text = fetch_page_text(url) if url else None
        if not page_text and record.get("hint_url") and url != record["hint_url"]:
            page_text = fetch_page_text(record["hint_url"])
        if not page_text:
            round2.setdefault(app, {})[field] = "unsure"
            print(f"{app}.{field}: page fetch failed -> unsure")
            continue

        extraction = reextract_field(client, app, field, page_text)
        quote = (extraction or {}).get("quote")
        value = (extraction or {}).get("value")

        if (value is not None and quote and _valid_value(field, value)
                and normalize(quote) in normalize(page_text)):
            record["data"][field] = value
            record["data"].setdefault("raw_notes", "")
            record["data"]["raw_notes"] += (
                f' [pass2: "{field}" corrected, literal evidence: "{quote[:150]}"]'
            )
            round2.setdefault(app, {})[field] = "correct"
            print(f"{app}.{field}: FIXED -> {json.dumps(value)} (quote confirmed on page)")
        else:
            round2.setdefault(app, {})[field] = "unsure"
            print(f"{app}.{field}: could not literally confirm on page -> unsure")

    save_results(results)
    save_decisions(decisions)
    acc = compute_accuracy()
    print(f"\nbefore: {acc['accuracy_before']}, fixed: {acc['fixed_in_round2']}, "
          f"after: {acc['accuracy_after']}")
    return decisions


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    run_pass2()
