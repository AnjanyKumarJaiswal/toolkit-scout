from collections import Counter


def _category(rec: dict) -> str:
    return rec.get("list_category") or rec["data"]["category"]


def compute_patterns(records: dict) -> dict:
    ok = [r for r in records.values() if r["status"] == "ok"]
    data = [r["data"] for r in ok]

    auth_dist = Counter(m for d in data for m in d["auth_methods"])
    access_dist = Counter(d["access_model"] for d in data)
    verdict_dist = Counter(d["buildability_verdict"] for d in data)
    category_dist = Counter(_category(r) for r in ok)
    api_type_dist = Counter(t for d in data for t in d["api_surface"]["api_types"])
    mcp_count = sum(1 for d in data if d["has_existing_mcp"]["exists"])
    confidence_dist = Counter(d["confidence"] for d in data)
    category_mismatches = sum(
        1 for r in ok
        if r.get("list_category") and r["data"]["category"] != r["list_category"]
    )

    self_serve = {"self_serve_free", "self_serve_trial"}
    per_category = {}
    for cat in sorted(category_dist):
        cat_data = [r["data"] for r in ok if _category(r) == cat]
        n = len(cat_data)
        ready = sum(1 for d in cat_data if d["buildability_verdict"] == "ready_today")
        ss = sum(1 for d in cat_data if d["access_model"] in self_serve)
        per_category[cat] = {
            "total": n,
            "ready_today": ready,
            "self_serve": ss,
            "self_serve_pct": round(100 * ss / n) if n else 0,
            "ready_pct": round(100 * ready / n) if n else 0,
        }

    blockers = Counter(
        d["blocker_if_any"].strip().lower()
        for d in data
        if d["buildability_verdict"] == "blocked" and d["blocker_if_any"]
    )

    return {
        "n_ok": len(ok),
        "n_failed": len(records) - len(ok),
        "auth_distribution": dict(auth_dist.most_common()),
        "access_model_distribution": dict(access_dist.most_common()),
        "verdict_distribution": dict(verdict_dist.most_common()),
        "category_distribution": dict(category_dist.most_common()),
        "api_type_distribution": dict(api_type_dist.most_common()),
        "existing_mcp_count": mcp_count,
        "confidence_distribution": dict(confidence_dist.most_common()),
        "category_mismatches": category_mismatches,
        "per_category": per_category,
        "top_blockers": dict(blockers.most_common(5)),
        "self_serve_total": sum(
            v for k, v in access_dist.items() if k in self_serve),
    }
