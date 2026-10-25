# ExperimentOS

> **AI that doesn't just answer questions. It runs experiments to find out.**

ExperimentOS is an **autonomous experimentation engine that turns AI/ML research questions into executable
experiments and uses measured evidence to decide what to test next.**

```text
Typical assistant      Question → Answer

ExperimentOS           Question → Hypothesis → Experiment → Code → Execution → Measurements
                                → Evidence → Conclusion → Next Experiment ↺
```

The core innovation is not "AI can write experiment code". It is that **the agent closes the loop between
hypothesis, execution, evidence and the next hypothesis** — and every claim it makes is traceable to a measurement.

Built for the **Nebius × NVIDIA Global AI Hackathon** — *Best Apps and Agents* track.

| | |
|---|---|
| **Live demo** | <https://experimentos-web.onrender.com> — click **Run Featured Experiment** (free hosting: the first visit after 15 idle minutes takes ~1 min to wake up) |
| **API** | <https://experimentos-api-ijcq.onrender.com/health> |
| **NVIDIA model** | Nemotron 3 Super 120B (reasoning) + Nemotron 3 Nano 30B (fast tasks) |
| **Nebius service** | Token Factory — every reasoning step at runtime |
| **Tavily** | Live web search for existing evidence before every new experiment |
| **License** | MIT |

---

## What it does

Give ExperimentOS a research question such as *"Does increasing RAG retrieval depth improve answer accuracy?"*.
It then, autonomously:

1. **Understands** the question and maps it onto an executable experiment space (Nemotron, fast tier).
2. **Searches existing evidence** with Tavily (optional) and identifies the research gap.
3. **Forms a falsifiable hypothesis** — rejected and regenerated if it is vague (deterministic quality gate).
4. **Designs a controlled experiment** — independent/dependent/controlled variables, baseline, configurations, metrics, success criteria (Pydantic-validated JSON).
5. **Validates** the design with 9 checks (independent variable, measurable DV, baseline, ≥2 configurations, dataset, metric, compute budget, code syntax, permitted libraries). Failures go back to Nemotron for revision — max 3 attempts.
6. **Generates executable Python** (`ExperimentCodeGenerator`) against a small, safe experiment SDK.
7. **Submits the job** to a sandbox — a local isolated subprocess, or a **Nebius AI Cloud Serverless AI Job**.
8. **Executes** a real RAG pipeline over a bundled, deterministic dataset — every number is measured.
9. **Computes statistics in Python** — Wilson 95% CIs, paired bootstrap CIs, exact McNemar tests, trend & plateau detection.
10. **Analyzes** the evidence with Nemotron, which may only cite numbers that exist in the measurements (enforced).
11. **Decides**: SUPPORTED · PARTIALLY SUPPORTED · REJECTED · INCONCLUSIVE.
12. **Proposes the next experiment** — and one click runs it, creating a research trail.

Every state transition, tool call, Nemotron call and measurement is streamed live to the UI over SSE.

## Why it exists

LLM assistants answer research questions from what they already know. For empirical questions about AI systems
— *does reranking help? where does retrieval depth stop paying off?* — the honest answer is "it depends; measure
it". ExperimentOS makes measuring the default: it formulates, executes and interprets controlled experiments, then
uses what it learned to choose the next one.

---

## Architecture

```text
                         ┌──────────────── Frontend (Next.js) ────────────────┐
                         │ Research Lab · live Agent Timeline (SSE) · Results │
                         │ Evidence · Evidence Graph · Next Experiment · Trail │
                         └──────────────────────────┬─────────────────────────┘
                                                    │ REST + Server-Sent Events
                         ┌──────────────────────────▼─────────────────────────┐
                         │           FastAPI  ·  Experiment Agent              │
                         │   one explicit state machine (agent/orchestrator)   │
                         └──┬──────────────┬───────────────┬───────────────┬──┘
                            │              │               │               │
                ┌───────────▼──┐  ┌────────▼───────┐ ┌─────▼──────┐ ┌──────▼───────┐
                │   Planner    │  │ Code Generator │ │  Analyzer  │ │   Tavily     │
                │ hypothesis + │  │ + AST policy   │ │ + grounding│ │  (optional)  │
                │ design + val.│  │                │ │ + stats    │ │              │
                └──────┬───────┘  └───────┬────────┘ └─────┬──────┘ └──────────────┘
                       │                  │                │
          ┌────────────▼──────────────────▼────────────────▼───────┐
          │ Nebius Token Factory  →  NVIDIA Nemotron (reasoning)    │
          └─────────────────────────────────────────────────────────┘
                                          │ validated code
          ┌───────────────────────────────▼─────────────────────────┐
          │ Experiment Runner                                       │
          │   EXECUTION_MODE=local  → isolated sandbox subprocess   │
          │   EXECUTION_MODE=nebius → Nebius AI Cloud Serverless Job │
          └─────────────────────────────────────────────────────────┘
```

**Lifecycle:** `CREATED → PLANNING → VALIDATING → GENERATING_CODE → QUEUED → RUNNING → ANALYZING → COMPLETED`
(plus `FAILED` / `CANCELLED`; legal revision loops: `VALIDATING → PLANNING`, `RUNNING → GENERATING_CODE`).
Transitions are enforced in `app/models/experiment.py`.

**Design principle — LLM reasoning vs deterministic computation.**

| Nemotron (LLM)                                   | Python (deterministic)                                       |
|--------------------------------------------------|--------------------------------------------------------------|
| hypothesis, experiment design, code, interpretation, next experiment | metrics, statistics, aggregation, validation, execution, grounding checks |

One orchestrator with specialised components — no multi-agent swarm — so the loop is readable in a single file
(`backend/app/agent/orchestrator.py`).

---

## Demo

**Featured experiment** (one click, no configuration): *"Does increasing the number of retrieved documents improve
RAG answer accuracy?"* on the bundled **DEMO DATASET** `rag-eval-v1`, seed 42.

Demo flow (~2–3 minutes):

1. **Question** — click **Run Featured Experiment**.
2. **Agent** — watch the live timeline: hypothesis → design → validation (9 checks) → code → job.
3. **Nebius** — the *Nebius × NVIDIA* panel shows `Nebius Token Factory → NVIDIA Nemotron → plan` with the exact
   models, number of calls and tokens used, and where the 160 evaluations ran (the local sandbox in the hosted demo).
4. **Results** — real chart of accuracy (95% CI) and retrieval recall per configuration; evidence table with paired tests.
5. **Analysis** — the hypothesis verdict, findings with clickable run-level evidence, "every number verified".
6. **Next experiment** — e.g. *k=20 + reranking vs best plain top-k* → **RUN NEXT EXPERIMENT**.

---

## Nebius Integration

Nebius is a runtime dependency, not a README mention.

| Component | Where in code | What it does | Why |
|---|---|---|---|
| **Nebius Token Factory** | `backend/app/llm/nebius_client.py` | OpenAI-compatible `POST {NEBIUS_BASE_URL}/chat/completions` for every reasoning step. Each call is logged as an `llm_call` event (model, latency, tokens) and shown in the UI. | Hosted, OpenAI-compatible access to NVIDIA Nemotron with no GPU management. |
| **Nebius AI Cloud — Serverless AI Jobs** *(optional; implemented but **not used in the hosted demo** and not yet verified against a live job — the demo runs on a Token Factory trial and executes experiments in the app's own sandbox)* | `backend/app/execution/nebius_jobs.py`, `docker/runner.Dockerfile` | With `EXECUTION_MODE=nebius`: `nebius ai job create --image <runner> --inject-file experiment.py:/opt/experimentos/job/experiment.py --platform cpu-d3 --preset 4vcpu-16gb --async`, then streams `nebius ai logs <job>` (live progress events) and polls `nebius ai job get-by-name` until terminal. Results return via a delimited JSON block in the logs. | Generated code runs in an ephemeral, credential-free container instead of on the API host — the production isolation boundary. |

```text
Nebius Token Factory  →  Nemotron  →  hypothesis / plan / code / analysis / next experiment   (live demo)
Nebius AI Cloud       →  Serverless AI Job  →  experiment execution                           (optional path)
```

### Where Token Factory accelerated the workflow

Measured on a live run of the featured experiment (question → hypothesis → plan → code → execution → analysis →
next experiment): **the whole loop finished in 42 s with 8 Token Factory calls (~23k tokens)**.

| Step | Model | Latency | Tokens |
|---|---|---|---|
| understand_question | Nemotron 3 Nano 30B | 1.8 s | 1,017 |
| create_hypothesis | Nemotron 3 Super 120B | 4.1 s | 1,533 |
| design_experiment | Nemotron 3 Super 120B | 8.2 s | 3,090 |
| generate_experiment_code | Nemotron 3 Super 120B | 3.6 s | 1,651 |
| analyze_results | Nemotron 3 Super 120B | 6.3 s | 5,287 |
| create_next_experiment (+1 retry) | Nemotron 3 Super 120B | 5.9 s + 9.3 s | 10,413 |

- **OpenAI-compatible API** — integration is a single `httpx` client; no SDK, no GPU provisioning.
- **Two model tiers on one endpoint** — the cheap Nano model handles parsing, the Super model handles reasoning,
  switched by configuration only.
- **First-try structured output** — Nemotron's JSON passed the schema, falsifiability, plan-validation and
  number-grounding checks on the first attempt for every step except one (since fixed: the model wrote a
  descriptive phrase where an exact parameter name was required).
- Since that run, prompts were trimmed ~68% for the analysis steps and identical requests are cached, cutting
  token use further.

If `EXECUTION_MODE=nebius` but the CLI or image is missing, the agent says so in the timeline and (with
`NEBIUS_JOB_FALLBACK_LOCAL=true`) falls back to the local sandbox rather than failing silently.

## NVIDIA Integration

ExperimentOS uses **NVIDIA Nemotron** open models served by Nebius Token Factory. Model IDs are configured, never
hard-coded — copy them from the Token Factory catalog (NVIDIA → Nemotron):

| Variable | Tier | Used for | Suggested (verify in catalog) |
|---|---|---|---|
| `NEBIUS_MODEL` | reasoning | hypothesis, experiment design, code generation, analysis, next experiment | a large Nemotron, e.g. `nvidia/nemotron-3-super-120b-a12b` or `nvidia/Llama-3_1-Nemotron-Ultra-253B-v1` |
| `NEBIUS_FAST_MODEL` | fast | question parsing, research summarisation | a small Nemotron (Nano); defaults to `NEBIUS_MODEL` |

**Why Nemotron:** strong structured reasoning and JSON adherence for planning, competent Python generation for
the experiment harness, and open weights — the same model family can be self-hosted on Nebius AI Cloud.
Nemotron reasoning traces (`<think>…</think>`) are stripped before parsing.

**Never trusting raw LLM output.** Every Nemotron response is parsed into a Pydantic model; hypotheses pass a
falsifiability gate; plans pass 7 structural checks; code passes an AST safety policy; analyses are checked so that
**every number appears in the computed statistics** and every cited run exists. Each gate retries at most 3 times
with the specific failure fed back, then falls back to a safe deterministic path (labelled in the UI).

## Tavily Integration

Research-discovery layer (`backend/app/research/tavily.py`), **enabled in the hosted demo** and called at runtime for
every new research question when `TAVILY_API_KEY` is set:

```text
Research question → Tavily search (runtime) → Nemotron summarises: known findings, assumptions,
                    research gap, what is testable locally → hypothesis & experiment design target the gap
```

Sources are stored per experiment (`research_sources` table) and shown in the UI ("Existing evidence · Tavily").
Results for an identical query are cached, which saves Tavily credits and keeps the downstream Nemotron prompts
identical. If Tavily is missing or fails, the loop continues unchanged.

---

## Tech Stack

- **Frontend:** Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS 4, Recharts, SSE (`EventSource`)
- **Backend:** Python 3.11+, FastAPI, Pydantic v2, httpx, asyncio, SQLite
- **LLM:** NVIDIA Nemotron via Nebius Token Factory · **Execution:** local sandbox / Nebius Serverless AI Jobs
- **Research:** Tavily (optional) · **Tests:** pytest (mocked LLM), Vitest + Testing Library

## Installation

Prerequisites: Python ≥ 3.11, Node ≥ 20.

```bash
git clone <your-fork-url> experimentos && cd experimentos
cp .env.example .env            # then fill in NEBIUS_API_KEY / NEBIUS_MODEL

# backend
cd backend
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt      # Windows: .venv\Scripts\pip ...
cd ..

# frontend
cd frontend && npm install && cd ..
```

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `NEBIUS_API_KEY` | — | Token Factory API key (required for Nemotron) |
| `NEBIUS_BASE_URL` | `https://api.tokenfactory.nebius.com/v1/` | Token Factory endpoint |
| `NEBIUS_MODEL` | — | Nemotron reasoning model ID |
| `NEBIUS_FAST_MODEL` | `NEBIUS_MODEL` | Nemotron fast model ID |
| `ALLOW_OFFLINE_FALLBACK` | `true` | Without a key: run with the deterministic offline planner (loudly labelled) instead of returning 503 with setup instructions |
| `LLM_CACHE` | `true` | Replay identical Nemotron requests from `backend/.llm_cache/` (labelled "cached replay, no tokens used" in the UI) — keeps Token Factory usage low when re-running the same experiment |
| `LLM_DAILY_TOKEN_BUDGET` | `300000` | Daily Nemotron token cap (UTC day, persisted). New experiments get HTTP 429 when spent; a running one finishes on the rule-based path |
| `LLM_MAX_CALLS_PER_EXPERIMENT` | `20` | Hard cap on live Nemotron calls per experiment (cache hits are free) |
| `MAX_CONCURRENT_EXPERIMENTS` / `EXPERIMENT_RATE_LIMIT_PER_MINUTE` | `2` / `6` | Launch guardrails (HTTP 429 with a clear message) |
| `TAVILY_API_KEY` | — | Enables research discovery |
| `DATABASE_URL` | `sqlite:///./experimentos.db` | SQLite path (relative to `backend/`) |
| `EXECUTION_MODE` | `local` | `local` sandbox or `nebius` Serverless Jobs |
| `EXECUTION_TIMEOUT_SECONDS` / `EXECUTION_MEMORY_MB` | `240` / `1024` | Sandbox limits |
| `NEBIUS_JOB_IMAGE`, `NEBIUS_PROJECT_ID`, `NEBIUS_JOB_PLATFORM`, `NEBIUS_JOB_PRESET`, `NEBIUS_JOB_TIMEOUT` | —, —, `cpu-d3`, `4vcpu-16gb`, `1h` | Serverless job settings |
| `CORS_ORIGINS` / `CORS_ORIGIN_REGEX` | localhost:3000 / — | Allowed frontend origins (e.g. your Vercel URL) |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Backend URL seen by the browser |

If the key is missing, the backend logs exactly what to set, `/health` reports `"nebius": "not_configured"`, and
the UI shows an **OFFLINE MODE — Nemotron not used** banner. Measurements are identical in both modes; only the
language reasoning differs.

## Running Locally

```bash
# terminal 1 — API on :8000
cd backend && .venv/bin/uvicorn app.main:app --port 8000

# terminal 2 — UI on :3000
cd frontend && npm run dev
```

Open <http://localhost:3000> and click **Run Featured Experiment**. Health: `curl localhost:8000/health`
(`?deep=true` also pings Token Factory). Or with Docker: `docker compose up --build`.

## Deploying (free)

- **Render** — one click: *New → Blueprint* with [`render.yaml`](render.yaml) deploys the API (Docker) and the web app (Node) on the free tier.
- **Hugging Face Spaces + Vercel** — more free resources, sleeps only after 48 h.

Both are tested under their free-tier limits; step-by-step instructions in [DEPLOY.md](DEPLOY.md).

## Running with Nebius

1. **Token Factory:** set `NEBIUS_API_KEY`, `NEBIUS_MODEL` (and optionally `NEBIUS_FAST_MODEL`). Restart the
   backend; `/health` should report `"llm_mode": "nemotron"`.
2. **Serverless execution:** install and authenticate the [Nebius CLI](https://docs.nebius.com/cli), then build
   and push the runner image:
   ```bash
   docker build -f docker/runner.Dockerfile -t <registry>/experimentos-runner:1 .
   docker push <registry>/experimentos-runner:1
   ```
   Set `EXECUTION_MODE=nebius`, `NEBIUS_JOB_IMAGE=<registry>/experimentos-runner:1`, and `NEBIUS_PROJECT_ID`.
   The timeline will show `Nebius job <id> created on cpu-d3 (4vcpu-16gb)` and live job states.
3. **Hosting the app:** `docker compose up -d --build` on a Nebius AI Cloud VM (set `NEXT_PUBLIC_API_URL` and
   `CORS_ORIGINS` to the public URLs).

## Running Experiments

- **UI:** type a question (or pick an example) → **Run Experiment**; or **Run Featured Experiment**.
- **API:**

| Method | Path | |
|---|---|---|
| `POST` | `/experiments` | `{"research_question": "...", "use_research": true}` |
| `POST` | `/experiments/featured` | canonical demo |
| `GET` | `/experiments` | list + dashboard counts |
| `GET` | `/experiments/{id}` | full state, runs, events, sources, children |
| `GET` | `/experiments/{id}/status` | lifecycle status + execution progress |
| `GET` | `/experiments/{id}/results` | per-run metrics, per-question records, statistics, analysis |
| `GET` | `/experiments/{id}/events` | **SSE** stream of agent events (replay + live) |
| `POST` | `/experiments/{id}/next` | run the proposed next experiment |
| `POST` | `/experiments/{id}/cancel` | cancel |
| `GET` | `/datasets`, `/datasets/{id}` | bundled dataset metadata & questions |
| `GET` | `/health` | configuration status (never exposes keys) |

**Supported experiment space** (MVP: RAG): `retrieval_k`, `chunk_size`, `chunk_overlap`, `retriever`
(`bm25` / `embedding` / `hybrid`), `reranker` (`none` / `cross_lite`) + `rerank_top_n`, `max_context_tokens`,
`reader_position_bias`; metrics `accuracy`, `retrieval_recall`, `context_tokens`, `latency_ms`, `est_llm_latency_ms`.
Out-of-scope questions fail gracefully with an explanation.

---

## Security

AI-generated code is treated as untrusted. Defence in depth:

1. **Static AST policy** (`execution/code_policy.py`): import allow-list (`experimentos_sdk, math, statistics,
   random, json, itertools, functools, collections, time, typing`); bans `eval/exec/compile/open/__import__/
   getattr/...`, `os/sys/subprocess/socket`, any `_`-prefixed attribute, dunder strings, async code; size limits.
2. **Process isolation:** a separate interpreter in isolated mode (`python -I -B`), started with an **empty
   environment** (no API keys or credentials), `stdin` closed, in a throw-away working directory.
3. **Restricted builtins:** no `open/eval/exec/compile/input/globals/vars/getattr...`; `__import__` resolves only allow-listed modules.
4. **PEP 578 audit hook:** vetoes process spawning, `os.system`, sockets/network, `ctypes`, filesystem
   mutation/listing, env mutation, and any file access outside the working directory (reads of the Python
   stdlib are allowed).
5. **Limits:** wall-clock timeout, output-size cap; on POSIX also CPU-seconds, address space, file size and
   open-file `rlimit`s. Results are schema-validated and **recomputed** from per-question records before use.

> **LOCAL DEVELOPMENT MODE vs PRODUCTION / NEBIUS JOB MODE.** Python-level sandboxing is defence in depth, not a
> hard security boundary. On Windows there are no kernel resource limits (timeout + output cap only), and the UI
> labels this. For untrusted workloads use `EXECUTION_MODE=nebius`: code runs in an ephemeral, non-root,
> credential-free Nebius Serverless container containing only Python, the SDK and the dataset.

## Guardrails

| Guardrail | Where | Behaviour |
|---|---|---|
| Daily token budget | `llm/usage.py` | Checked **before** each request; usage persisted to `backend/.llm_cache/usage.json`; shown on the Settings page |
| Per-experiment call cap | `llm/nebius_client.py` | Each experiment gets its own allowance; cache replays are exempt |
| Graceful degradation | `agent/orchestrator.py::_guarded` | If a limit trips mid-run, the experiment finishes on the rule-based path — paid-for measurements are never discarded |
| Response cache | `LLM_CACHE` | Identical requests are replayed, labelled "cached replay, no tokens used" |
| Launch limits | `api/experiments.py` | Concurrency limit, per-client rate limit, budget pre-check (HTTP 429) |
| One follow-up per proposal | `POST /experiments/{id}/next` | A second click returns 409 with the existing experiment; the UI shows *Open experiment* instead |
| Input sanitising | `CreateExperiment` | Control/zero-width characters stripped, whitespace collapsed, must contain words |
| Hypothesis ↔ plan | `validate_experiment` (check 1) | The plan must vary the hypothesis's independent variable |
| Plan ↔ results | `evaluation/metrics.py` | Every run must have executed exactly the planned parameters (defaults included) and its metrics must be recomputable from per-question records |
| Grounded analysis | `evaluation/grounding.py` | Every number must exist in the computed statistics; SUPPORTED needs a significant difference |
| Code policy | `execution/code_policy.py` | Import allow-list, no dunder/private access, no module traversal (`json.codecs`…), no `while` loops, size limits |
| Dataset integrity | `evaluation/dataset.py` | Startup refuses a corrupted benchmark (ids, gold passages, answer vocabulary) |

Prompts sent to Nemotron carry statistics once (readable facts + a compact JSON of only the varied parameters),
~68% smaller than the naive dump — about 1.1k tokens saved on every analysis and next-experiment call.

## Project Structure

```text
backend/
├── app/
│   ├── main.py · config.py
│   ├── api/            experiments.py (incl. SSE) · datasets.py · health.py
│   ├── agent/          orchestrator.py · hypothesis.py · planner.py · code_generator.py
│   │                   analyzer.py · next_experiment.py · prompts.py · offline.py · context.py
│   ├── llm/            nebius_client.py
│   ├── execution/      runner.py · sandbox.py · nebius_jobs.py · code_policy.py
│   │   └── runtime/    bootstrap.py · experimentos_sdk/ (rag.py, runtime.py)   ← shipped into the job image
│   ├── research/       tavily.py
│   ├── evaluation/     statistics.py · metrics.py · grounding.py
│   ├── storage/        database.py · repositories.py
│   └── models/         experiment.py · results.py · agent.py
├── data/rag_eval.json  · scripts/build_dataset.py
└── tests/              95 tests, mocked Nemotron
frontend/
├── app/                Research Lab · experiments/[id] · experiments · datasets · history · settings
├── components/         ResearchInput · AgentTimeline · ExperimentPlan · ResultsChart · EvidencePanel
│                       EvidenceGraph · CodeViewer · NextExperiment · AnalysisPanel · NebiusPanel · ExecutionLog
├── lib/ · types/ · tests/
docker/                 backend · frontend · runner (Nebius job image) Dockerfiles
```

## Example Experiment

Measured by the bundled pipeline (deterministic — you will get the same numbers; seed 42, `rag-eval-v1`):

**Experiment #001 — RAG retrieval depth** (BM25, 128-word chunks, extractive reader)

| Run | retrieval_k | Accuracy | Retrieval recall | Context tokens |
|---|---|---|---|---|
| k3 (baseline) | 3 | 70.0% | 85.0% | 117 |
| k5 | 5 | 72.5% | 95.0% | 197 |
| k10 | 10 | 67.5% | 97.5% | 391 |
| k20 | 20 | 67.5% | 100.0% | 765 |

Recall rises to 100%, but accuracy does not follow — no difference versus the baseline is significant (exact McNemar p = 1.000 for every run), so the
hypothesis *"increasing k from 3 to 10 improves accuracy"* is **INCONCLUSIVE**. The evidence points at
distractors: deeper retrieval brings in look-alike decoy passages and pushes the gold passage into the middle of
the context. **Next experiment proposed:** rerank a deeper candidate list.

**Experiment #002 — Reranking vs retrieval depth** (created by clicking *Run Next Experiment*)

| Run | Configuration | Accuracy | vs baseline |
|---|---|---|---|
| baseline_best | k=5, no reranking | 72.5% | — |
| k20_rerank_top5 | k=20 → rerank → top 5 | **92.5%** | **+20.0 pp** (paired 95% CI [+7.5, +32.5]), 8 gained / 0 lost, McNemar **p = 0.008** |
| k20_rerank_top10 | k=20 → rerank → top 10 | 77.5% | +5.0 pp, p = 0.688 |

Hypothesis **SUPPORTED**. Next proposed: chunk size, holding the reranked configuration fixed.

(With Nemotron enabled, the wording of hypotheses, plans and analyses differs and the agent may choose different
configurations; the measurements for any given configuration are always the same.)

## Reproducibility

- **Seed:** 42 (experiment code calls `set_seed(42)`; bootstrap CIs use a fixed seed; Python hash seed fixed in the sandbox).
- **Dataset version:** `rag-eval-v1` — 40 questions, 140 passages, fictional entities (no model prior knowledge),
  two look-alike decoys per entity. Rebuild byte-identically: `python backend/scripts/build_dataset.py`; its
  SHA-256 is shown on the Datasets page and in `/health`.
- **Pipeline:** pure Python, no external services, no randomness — identical configurations give identical
  per-question results (`tests/test_sandbox_and_execution.py::test_rag_pipeline_is_deterministic`).
- **What is simulated, honestly:** the *reader* is a deterministic extractive model with a documented
  lost-in-the-middle position bias (`reader_position_bias`), not a generative LLM; `est_llm_latency_ms` is a modelled
  latency (`180 ms + 0.12 ms/token`), clearly labelled. Retrieval, reranking, chunking, accuracy and recall are real
  computations over the dataset; nothing in the results is hard-coded.

### Tests

```bash
cd backend && .venv/bin/python -m pytest -q     # 95 tests — schemas, validation, statistics, parsing,
                                                 # state machine, sandbox, LLM client, grounding, API, end-to-end loop
cd frontend && npm test                          # 16 tests — creation, status, results, errors, next-experiment flow
```

No test needs a Nebius API key (Nemotron is mocked via `tests/fakes.py`; Token Factory HTTP via `httpx.MockTransport`).

## Hackathon Submission

- **Track:** Best Apps and Agents
- **Live demo:** <https://experimentos-web.onrender.com> · **Code:** <https://github.com/NA-V10/ExperimentOS>
- **Nebius:** Token Factory — runtime reasoning for every agent step (live). AI Cloud Serverless Jobs — optional
  execution backend, implemented but not used in the hosted demo.
- **NVIDIA:** Nemotron 3 Super 120B (reasoning) and Nemotron 3 Nano 30B (fast tasks) for all language steps
- **Tavily:** live runtime search (`POST https://api.tavily.com/search`) before each new experiment; Nemotron
  summarises the sources into known findings and a research gap that the hypothesis targets
- **License:** MIT

Compliance checklist:

```text
[x] Application runs locally and on Render (https://experimentos-web.onrender.com)
[x] Nebius Token Factory + NVIDIA Nemotron verified live (full loop, 8 calls, 42 s)
[x] Experiment actually executes; results are measured, not hard-coded
[x] Public GitHub repository with MIT license
[x] README with setup instructions; Nebius, NVIDIA and Tavily usage documented
[x] Tavily runtime search call live in the hosted demo
[x] Generated code is sandboxed · error states tested · no API keys committed (.env is git-ignored)
[ ] Nebius AI Cloud job execution verified live (optional path, not used in the demo)
[ ] 3-minute public demo video
```

## License

[MIT](LICENSE)
