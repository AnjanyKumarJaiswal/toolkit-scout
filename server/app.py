import logging
import threading
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from pipeline.analysis import compute_patterns
from pipeline.review import (
    compute_accuracy,
    create_sample,
    load_decisions,
    load_sample,
    save_decisions,
)
from pipeline.runner import DATA_DIR, load_results, run_pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("toolkit_scout")

app = Flask(__name__)
CORS(app)

_run_lock = threading.Lock()
_run_state = {"running": False, "last_meta": None, "error": None}


@app.get("/")
def health():
    return jsonify({"service": "toolkit-scout", "status": "ok"})


@app.get("/api/results")
def get_results():
    results = load_results()
    return jsonify({
        "meta": results["meta"],
        "records": results["records"],
        "patterns": compute_patterns(results["records"]),
        "verification": {
            "accuracy": compute_accuracy(),
            "decisions": load_decisions(),
        },
    })


@app.get("/api/results/<app_name>")
def get_result(app_name: str):
    record = load_results()["records"].get(app_name)
    if record is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(record)


@app.get("/api/run/status")
def run_status():
    return jsonify(_run_state)


@app.post("/api/run")
def start_run():
    if _run_state["running"]:
        return jsonify({"error": "a run is already in progress"}), 409

    body = request.get_json(silent=True) or {}
    app_list = DATA_DIR / body.get("app_list", "apps_test.json")
    if not app_list.resolve().is_relative_to(DATA_DIR.resolve()) or not app_list.exists():
        return jsonify({"error": f"app list not found: {app_list.name}"}), 400
    limit = body.get("limit")
    retry_failed = bool(body.get("retry_failed", False))

    def worker(path: Path, limit, retry_failed):
        with _run_lock:
            _run_state.update(running=True, error=None)
            try:
                meta = run_pipeline(path, limit=limit, retry_failed=retry_failed)
                _run_state["last_meta"] = meta
            except Exception as e:
                log.exception("run crashed")
                _run_state["error"] = str(e)
            finally:
                _run_state["running"] = False

    threading.Thread(target=worker, args=(app_list, limit, retry_failed),
                     daemon=True).start()
    return jsonify({"started": True, "app_list": app_list.name, "limit": limit}), 202


@app.get("/review")
def review_page():
    return send_from_directory("static", "review.html")


@app.post("/api/review/sample")
def new_sample():
    body = request.get_json(silent=True) or {}
    payload = create_sample(n=int(body.get("n", 18)), seed=body.get("seed"))
    return jsonify(payload)


@app.get("/api/review/data")
def review_data():
    sample = load_sample()
    if sample is None:
        return jsonify({"error": "no sample yet, POST /api/review/sample first"}), 404
    records = load_results()["records"]
    return jsonify({
        "sample": sample,
        "records": {name: records[name] for name in sample["apps"] if name in records},
        "decisions": load_decisions(),
    })


@app.post("/api/review/decision")
def save_decision():
    body = request.get_json(silent=True) or {}
    app_name = body.get("app_name")
    field = body.get("field")
    verdict = body.get("verdict")
    round_key = body.get("round", "round1")
    if not app_name or not field or verdict not in ("correct", "incorrect", "unsure"):
        return jsonify({"error": "need app_name, field, verdict(correct|incorrect|unsure)"}), 400
    decisions = load_decisions()
    decisions.setdefault(round_key, {}).setdefault(app_name, {})[field] = verdict
    save_decisions(decisions)
    return jsonify({"saved": True})


@app.get("/api/review/accuracy")
def review_accuracy():
    return jsonify(compute_accuracy())


if __name__ == "__main__":
    app.run(debug=True, port=5001)
