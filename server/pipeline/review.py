import json
import random
from datetime import datetime, timezone
from pathlib import Path

from .runner import DATA_DIR, load_results

SAMPLE_PATH = DATA_DIR / "review_sample.json"
DECISIONS_PATH = DATA_DIR / "review_decisions.json"

REVIEW_FIELDS = [
    "category", "auth_methods", "access_model", "api_surface",
    "has_existing_mcp", "buildability_verdict", "evidence_url",
]


def create_sample(n: int = 18, seed: int | None = None) -> dict:
    results = load_results()
    ok_apps = [name for name, r in results["records"].items() if r["status"] == "ok"]
    rng = random.Random(seed)
    sample = sorted(rng.sample(ok_apps, min(n, len(ok_apps))))
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "n": len(sample),
        "apps": sample,
    }
    SAMPLE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def load_sample() -> dict | None:
    if SAMPLE_PATH.exists():
        return json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    return None


def load_decisions() -> dict:
    if DECISIONS_PATH.exists():
        return json.loads(DECISIONS_PATH.read_text(encoding="utf-8"))
    return {"round1": {}, "round2": {}}


def save_decisions(decisions: dict) -> None:
    DECISIONS_PATH.write_text(json.dumps(decisions, indent=2), encoding="utf-8")


def compute_accuracy() -> dict:
    decisions = load_decisions()
    round1, round2 = decisions.get("round1", {}), decisions.get("round2", {})

    per_field = {f: {"correct": 0, "incorrect": 0, "unsure": 0} for f in REVIEW_FIELDS}
    total_correct = total_judged = 0
    for app, fields in round1.items():
        for field, verdict in fields.items():
            if field not in per_field or verdict not in ("correct", "incorrect", "unsure"):
                continue
            per_field[field][verdict] += 1
            if verdict in ("correct", "incorrect"):
                total_judged += 1
                if verdict == "correct":
                    total_correct += 1

    fixed = sum(
        1 for app, fields in round2.items()
        for field, verdict in fields.items()
        if verdict == "correct" and round1.get(app, {}).get(field) == "incorrect"
    )

    accuracy_before = round(total_correct / total_judged, 4) if total_judged else None
    accuracy_after = (
        round((total_correct + fixed) / total_judged, 4) if total_judged else None
    )
    return {
        "per_field": {
            f: {
                **counts,
                "accuracy": round(
                    counts["correct"] / (counts["correct"] + counts["incorrect"]), 4)
                if (counts["correct"] + counts["incorrect"]) else None,
            }
            for f, counts in per_field.items()
        },
        "fields_judged": total_judged,
        "accuracy_before": accuracy_before,
        "fixed_in_round2": fixed,
        "accuracy_after": accuracy_after,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Create a review sample")
    parser.add_argument("--n", type=int, default=18)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()
    payload = create_sample(args.n, args.seed)
    print(f"sampled {payload['n']} apps -> {SAMPLE_PATH}")
