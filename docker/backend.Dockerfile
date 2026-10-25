# ExperimentOS API (FastAPI) — runs on Hugging Face Spaces (Docker), a Nebius AI Cloud VM,
# or any container host. Build context: the repository root.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

# Hugging Face Spaces runs containers as uid 1000; use the same user everywhere.
RUN useradd --create-home --uid 1000 user \
 && mkdir -p /data /tmp/experimentos-work \
 && chown -R user:user /data /tmp/experimentos-work

WORKDIR /home/user/app
COPY --chown=user backend/requirements.txt .
RUN pip install -r requirements.txt
COPY --chown=user backend/ .

USER user

# All mutable state lives in /data (HF persistent storage mounts there if enabled; otherwise it
# is reset on restart, which is fine for a demo). Sandbox scratch space goes to /tmp.
ENV DATABASE_URL=sqlite:////data/experimentos.db \
    LLM_CACHE_DIR=/data/llm_cache \
    WORK_ROOT=/tmp/experimentos-work \
    EXECUTION_MODE=local

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/health',timeout=4)"

# --proxy-headers: behind HF/Vercel proxies, use the real client IP (per-visitor rate limiting).
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
