import csv
import json
import logging
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from .researcher import research_app

log = logging.getLogger("toolkit_scout")

SERVER_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = SERVER_DIR / "data"
RESULTS_PATH = DATA_DIR / "results.json"


def load_app_list(path: Path) -> list[dict]:
    if path.suffix == ".json":
        apps = json.loads(path.read_text(encoding="utf-8"))
    elif path.suffix == ".csv":
        with path.open(encoding="utf-8-sig") as f:
            apps = [
                {"name": row["name"].strip(),
                 "hint_url": (row.get("hint_url") or "").strip() or None}
                for row in csv.DictReader(f)
            ]
    else:
        raise ValueError(f"unsupported app list format: {path.suffix}")
    seen, out = set(), []
    for app in apps:
        if app["name"] not in seen:
            seen.add(app["name"])
            out.append(app)
    return out


def load_results() -> dict:
    if RESULTS_PATH.exists():
        return json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    return {"meta": {}, "records": {}}


def save_results(results: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    tmp = RESULTS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(RESULTS_PATH)


def _recompute_meta(results: dict) -> None:
    records = results["records"].values()
    ok = [r for r in records if r["status"] == "ok"]
    results["meta"] = {
        "total_apps": len(results["records"]),
        "ok": len(ok),
        "failed": len(results["records"]) - len(ok),
        "total_estimated_usd": round(
            sum(r["cost"]["estimated_usd"] for r in records), 4),
        "total_web_search_calls": sum(
            r["cost"]["web_search_calls"] for r in records),
    }


def run_pipeline(app_list_path: Path, limit: int | None = None,
                 retry_failed: bool = False) -> dict:
    load_dotenv(SERVER_DIR / ".env")
    client = OpenAI()

    apps = load_app_list(app_list_path)
    if limit:
        apps = apps[:limit]

    results = load_results()
    for i, app in enumerate(apps, 1):
        existing = results["records"].get(app["name"])
        if existing and existing["status"] == "ok":
            continue
        if existing and existing["status"] == "research_failed" and not retry_failed:
            continue
        log.info("[%d/%d] researching %s ...", i, len(apps), app["name"])
        record = research_app(client, app["name"], app.get("hint_url"))
        if app.get("category"):
            record["list_category"] = app["category"]
        results["records"][app["name"]] = record
        _recompute_meta(results)
        save_results(results)

    _recompute_meta(results)
    save_results(results)
    log.info("run complete: %s", results["meta"])
    return results["meta"]


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    parser = argparse.ArgumentParser(description="Run the toolkit-scout research pipeline")
    parser.add_argument("app_list", type=Path)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--retry-failed", action="store_true")
    args = parser.parse_args()
    run_pipeline(args.app_list, limit=args.limit, retry_failed=args.retry_failed)
