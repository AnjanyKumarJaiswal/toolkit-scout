# toolkit-scout

A research pipeline that audits 100 SaaS apps to determine whether each could
become an AI-agent toolkit (an MCP server or agent-callable skill set) — built
for the Composio product-intern assignment.

For every app it researches: auth methods, self-serve vs gated access, API
surface, existing MCP status, and a buildability verdict — grounded in a live
web search, structured with a strict JSON schema, verified by hand on a random
sample, and aggregated into cross-cutting patterns.

## Architecture

```
client/  static HTML + vanilla CSS
   └── one fetch → GET /api/results

server/  Python + Flask (Render)
   ├── app.py                    stateless API
   └── pipeline/
       ├── schema.py             strict JSON schema (all enums locked)
       ├── researcher.py         1 web-search-grounded gpt-4o-mini call per app
       ├── runner.py             resumable batch runner → data/results.json
       ├── review.py             random sampling + accuracy tracking
       ├── verify_pass2.py       literal fetch-and-confirm for wrong claims
       └── analysis.py           pattern aggregates
```

- **Research**: one search-grounded OpenAI Responses API call per app with
  strict structured output. Search grounding uses Composio's
  `composio_search` toolkit (via the Composio SDK) when `COMPOSIO_API_KEY`
  is set, and falls back to OpenAI's built-in `web_search` tool otherwise.
  Failures never crash the run; they are stored as `research_failed`
  records with a reason.
- **Resumable**: results are saved after every app, so an interrupted run
  restarts where it left off.
- **Cost-visible**: tokens, search calls, and estimated USD are logged per app
  and totaled. The full 100-app run cost ~$1.16.
- **Verification**: 18 randomly sampled apps, 7 fields each, two loops plus
  a human check. Loop 1 (`agent_review.py`): a strict fact-checker agent
  fetches each evidence page and re-judges every claim against it. Loop 2
  (`verify_pass2.py`): flagged fields get a literal fetch-and-confirm pass —
  a correction is only accepted if its supporting quote appears verbatim in
  the page text. A human review UI (`/review`) allows manual overrides.

## Setup

```bash
cd server
python -m venv app
app\Scripts\pip install -r requirements.txt   # Windows
cp .env.example .env                          # add your OPENAI_API_KEY
```

## Running

```bash
cd server

# research pipeline (test set first, then all 100)
app\Scripts\python -m pipeline.runner data\apps_test.json
app\Scripts\python -m pipeline.runner data\apps_100.json
app\Scripts\python -m pipeline.runner data\apps_100.json --retry-failed

# API server
app\Scripts\python app.py            # http://localhost:5001

# verification
app\Scripts\python -m pipeline.review --n 18 --seed 42   # create sample
app\Scripts\python -m pipeline.agent_review               # loop 1: fact-checker agent
app\Scripts\python -m pipeline.verify_pass2               # loop 2: literal fetch-and-confirm
# optional human overrides: open http://localhost:5001/review
```

Frontend: serve or open `client/index.html` (it auto-targets
`http://localhost:5001` locally, the Render URL in production).

## API

| Endpoint | Description |
|---|---|
| `GET /api/results` | all records + pattern aggregates + verification stats |
| `GET /api/results/<app>` | single app record |
| `POST /api/run` | start a research run (`{"app_list": "apps_100.json"}`) |
| `GET /api/run/status` | run progress |
| `GET /review` + `/api/review/*` | human verification tooling |

## Deployment

- **Render** (backend): create a web service with root dir `server`, build
  command `pip install -r requirements.txt`, start command `gunicorn app:app`,
  and set the `OPENAI_API_KEY` environment variable.
  `data/results.json` is committed so the API serves data immediately.
- **Vercel** (frontend): deploy the `client/` folder as a static site. Update
  `BACKEND_BASE_URL` and `REPO_URL` at the top of the script in `index.html`.

## Stack

Python, Flask, flask-cors, gunicorn, OpenAI Responses API (`gpt-4o-mini`),
Composio SDK (`composio_search` toolkit for search grounding, with OpenAI
`web_search` fallback), requests, BeautifulSoup, vanilla HTML/CSS/JS. No
frameworks, no database, no paid search APIs.
