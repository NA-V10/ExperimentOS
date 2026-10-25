# Deploying ExperimentOS for free

Two free options. **Render** is the simplest: one blueprint deploys both parts from GitHub.

| | Render (recommended for simplicity) | Hugging Face Spaces + Vercel |
|---|---|---|
| Setup | 1 blueprint, both services | 2 services, 2 accounts |
| Free resources | 512 MB RAM, 0.1 CPU per service | 16 GB RAM, 2 vCPU (backend) |
| Sleeps after | **15 min** idle (~1 min cold start) | 48 h idle |
| Credit card | not required | not required |

Both were tested with Docker under their limits: on Render's 0.1 CPU / 512 MB the featured
experiment completes in ~27 s using ~84 MB, with results identical to local runs.

Reasoning runs on **NVIDIA Nemotron via Nebius Token Factory**; experiments run inside the backend
container (Linux sandbox with CPU/memory/file limits). Nebius AI Cloud is not used.

---

## Option A — Render (one blueprint)

1. **Push this repository to GitHub** (public — also a hackathon requirement).
2. Sign up at <https://dashboard.render.com/register> with GitHub (no card needed).
3. **New → Blueprint** → select the repo. Render reads [`render.yaml`](render.yaml) and shows two
   services: `experimentos-api` (Docker) and `experimentos-web` (Node).
4. When prompted, paste your **`NEBIUS_API_KEY`** (stored as a secret in Render, never in git).
5. **Apply.** The first build takes ~5–10 minutes. Then open:
   - API health: `https://experimentos-api.onrender.com/health` → `"llm_mode": "nemotron"`
   - App: `https://experimentos-web.onrender.com` → **Run Featured Experiment**

**If Render gives a different URL** (it appends a suffix when a name is taken, e.g.
`experimentos-api-x1y2.onrender.com`):
- `experimentos-web` → Environment → set `NEXT_PUBLIC_API_URL` to the API's real URL → **Manual Deploy**
  (it is baked in at build time, so a redeploy is required).
- `experimentos-api` → Environment → set `CORS_ORIGINS` to the web service's real URL.

**Render free-tier notes**
- Services **sleep after 15 minutes** without traffic; the first visit takes ~1 minute to wake
  both. Open the app yourself a minute before demoing or judging.
- The disk is **reset on every deploy/restart**: experiment history and the Nemotron response cache
  are cleared (re-running the featured experiment then makes live calls again).
- Free instances share 750 hours/month — plenty, because sleeping services don't use hours.
- The blueprint already applies public-demo guardrails: 100k tokens/day, 1 experiment at a time,
  4 launches/minute per visitor, sandbox memory sized for 512 MB.

---

## Option B — Hugging Face Spaces (backend) + Vercel (frontend)

### B1. Backend → Hugging Face Spaces

1. Sign up at <https://huggingface.co/join>.
2. Create a Space: <https://huggingface.co/new-space>
   - Name: `experimentos` · License: MIT · **SDK: Docker → Blank** · Hardware: **CPU basic (free)** · Public.
3. Create a **write** access token: <https://huggingface.co/settings/tokens> → *New token* → type *Write*.
4. In the Space → **Settings → Variables and secrets**, add:

   | Name | Type | Value |
   |---|---|---|
   | `NEBIUS_API_KEY` | **Secret** | your Token Factory key |
   | `NEBIUS_MODEL` | Variable | `nvidia/nemotron-3-super-120b-a12b` |
   | `NEBIUS_FAST_MODEL` | Variable | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` |
   | `LLM_DAILY_TOKEN_BUDGET` | Variable | `100000` *(public demo: anyone can click Run)* |
   | `MAX_CONCURRENT_EXPERIMENTS` | Variable | `1` |

5. Push the backend (from the repo root, Git Bash or PowerShell):

   ```bash
   # Git Bash
   export HF_TOKEN=hf_xxx            # the write token from step 3
   python deploy/huggingface/prepare_space.py --push <your-hf-username>/experimentos
   ```
   ```powershell
   # PowerShell
   $env:HF_TOKEN = "hf_xxx"
   python deploy/huggingface/prepare_space.py --push <your-hf-username>/experimentos
   ```

   The script stages only the backend (no `.env`, caches, databases or venvs) and refuses to push
   if anything secret-looking is staged.
6. Wait for the build (Space → *Logs*), then open `https://<user>-experimentos.hf.space/health`.
   You should see `"llm_mode": "nemotron"`.

### B2. Frontend → Vercel

1. Push this repository to GitHub (public).
2. Sign in at <https://vercel.com/signup> with GitHub → **Add New → Project** → import the repo.
3. Settings on the import screen:
   - **Root Directory:** `frontend` (Framework preset: Next.js is detected automatically)
   - **Environment Variable:** `NEXT_PUBLIC_API_URL` = `https://<user>-experimentos.hf.space`
4. **Deploy.** You get `https://<project>.vercel.app`.

### B3. Connect them (CORS)

Back in the Space → Settings → Variables, add:

| Name | Value |
|---|---|
| `CORS_ORIGINS` | `https://<project>.vercel.app` |
| `CORS_ORIGIN_REGEX` | `https://<project>.*\.vercel\.app` *(also allows Vercel preview deployments)* |

The Space restarts automatically. Open the Vercel URL → **Run Featured Experiment**.

---

### Option B notes

- **Sleep:** a free Space sleeps after 48 h without traffic; the first visit wakes it (~30–60 s).
  Open the site once before a judge does.
- **Data is reset when the Space restarts** (free tier has no persistent disk). That clears the
  experiment history and the Nemotron response cache. Optional paid persistent storage mounts at
  `/data`, where the app already keeps its database and cache.
- **Usage guardrails** protect your Token Factory trial on a public URL: daily token budget, per-run
  call cap, concurrency limit and per-visitor rate limit. Today's usage is on the **Settings** page.
- **Redeploy the backend:** re-run step B1.5. **Redeploy the frontend:** push to GitHub (Vercel
  rebuilds automatically). If you change `NEXT_PUBLIC_API_URL`, trigger a redeploy in Vercel —
  it is baked in at build time.
- **Test the backend image locally first** (optional, needs Docker):
  ```bash
  python deploy/huggingface/prepare_space.py
  docker build -t experimentos-api dist/hf-space
  docker run --rm -p 8000:8000 --env-file .env experimentos-api
  ```
