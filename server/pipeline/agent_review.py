import json
import logging

from dotenv import load_dotenv
from openai import OpenAI

from .researcher import MODEL
from .review import REVIEW_FIELDS, load_decisions, load_sample, save_decisions, compute_accuracy
from .runner import SERVER_DIR, load_results
from .verify_pass2 import fetch_page_text

log = logging.getLogger("toolkit_scout")

JUDGE_SCHEMA = {
    "name": "claim_judgments",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            field: {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "verdict": {"type": "string", "enum": ["correct", "incorrect", "unsure"]},
                    "reason": {"type": "string"},
                },
                "required": ["verdict", "reason"],
            }
            for field in REVIEW_FIELDS
        },
        "required": REVIEW_FIELDS,
    },
}

JUDGE_PROMPT = """\
You are a strict fact-checker. Below are claims an AI research agent made about
the app "{app}", followed by evidence. Judge EACH claim:

- "correct": the evidence (page text or your search findings) supports it
- "incorrect": the evidence contradicts it, or the claim asserts something the
  official docs clearly state differently (e.g. claiming an auth method the
  vendor has deprecated or does not offer)
- "unsure": evidence is insufficient to judge either way

Be strict: vague claims like "docs suggest an MCP exists" without a concrete
MCP server are NOT correct. An evidence_url is correct only if it is a real,
relevant page for this app's developer docs.

CLAIMS:
{claims}

EVIDENCE PAGE ({url}):
{page}
"""


def judge_app(client: OpenAI, app_name: str, record: dict) -> dict:
    data = record["data"]
    claims = {f: data[f] for f in REVIEW_FIELDS}
    url = data["evidence_url"]
    page = fetch_page_text(url)
    page_note = page if page else "(page could not be fetched — status error or timeout)"

    kwargs = {
        "model": MODEL,
        "input": JUDGE_PROMPT.format(
            app=app_name,
            claims=json.dumps(claims, indent=1),
            url=url,
            page=page_note,
        ),
        "text": {"format": {"type": "json_schema", **JUDGE_SCHEMA}},
        "max_output_tokens": 1200,
        "tools": [{"type": "web_search"}],
    }
    resp = client.responses.create(**kwargs)
    judgments = json.loads(resp.output_text)

    if page is None and judgments["evidence_url"]["verdict"] == "correct":
        judgments["evidence_url"] = {
            "verdict": "incorrect",
            "reason": "evidence_url could not be fetched (dead or blocked URL)",
        }
    return judgments


def run_agent_review() -> None:
    load_dotenv(SERVER_DIR / ".env")
    client = OpenAI()

    sample = load_sample()
    if not sample:
        raise SystemExit("no review sample — run pipeline.review first")
    records = load_results()["records"]

    decisions = load_decisions()
    decisions["round1"] = {}
    decisions["round1_reasons"] = {}
    decisions["round2"] = {}

    for i, app in enumerate(sample["apps"], 1):
        record = records.get(app)
        if not record or record["status"] != "ok":
            continue
        try:
            judgments = judge_app(client, app, record)
        except Exception as e:
            log.warning("judge failed for %s: %s", app, e)
            judgments = {f: {"verdict": "unsure", "reason": f"judge error: {e}"}
                         for f in REVIEW_FIELDS}
        decisions["round1"][app] = {f: j["verdict"] for f, j in judgments.items()}
        decisions["round1_reasons"][app] = {f: j["reason"] for f, j in judgments.items()}
        flags = [f for f, j in judgments.items() if j["verdict"] != "correct"]
        print(f"[{i}/{len(sample['apps'])}] {app}: "
              f"{'all correct' if not flags else 'flagged -> ' + ', '.join(flags)}")

    save_decisions(decisions)
    acc = compute_accuracy()
    print(f"\nfirst-pass accuracy: {acc['accuracy_before']}, "
          f"fields judged: {acc['fields_judged']}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    run_agent_review()
