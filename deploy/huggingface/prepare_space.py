"""Assemble (and optionally push) the Hugging Face Space that hosts the ExperimentOS API.

A Docker Space needs its own git repo with a Dockerfile and a README.md (YAML header) at
the root. This script builds that repo in dist/hf-space from the backend sources — never
copying secrets, caches, databases or virtualenvs.

Usage (from the repository root):
    python deploy/huggingface/prepare_space.py                       # build dist/hf-space only
    python deploy/huggingface/prepare_space.py --push <user>/<space> # build and push (needs HF_TOKEN)

Secrets (NEBIUS_API_KEY) are NEVER pushed: set them in the Space's Settings → Secrets.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "dist" / "hf-space"
SKIP_DIRS = {".venv", "__pycache__", ".pytest_cache", ".work", ".llm_cache", "tests", "node_modules"}
SKIP_SUFFIXES = {".db", ".db-wal", ".db-shm", ".log", ".pyc"}
SKIP_NAMES = {".env"}

SPACE_README = """---
title: ExperimentOS API
emoji: 🧪
colorFrom: green
colorTo: blue
sdk: docker
app_port: 8000
pinned: false
license: mit
short_description: Autonomous AI experimentation engine — API (Nemotron on Nebius)
---

# ExperimentOS API

Backend of **ExperimentOS** — *AI that doesn't just answer questions. It runs experiments to find out.*

- Health: `/health` · API docs: `/docs`
- Reasoning: NVIDIA Nemotron via Nebius Token Factory · Experiments run in a sandboxed subprocess in this container.

Configure in **Settings → Variables and secrets**:

| Name | Kind | Example |
|---|---|---|
| `NEBIUS_API_KEY` | **Secret** | your Token Factory key |
| `NEBIUS_MODEL` | Variable | `nvidia/nemotron-3-super-120b-a12b` |
| `NEBIUS_FAST_MODEL` | Variable | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` |
| `CORS_ORIGINS` | Variable | `https://your-app.vercel.app` |
| `CORS_ORIGIN_REGEX` | Variable | `https://your-app.*\\.vercel\\.app` |
| `LLM_DAILY_TOKEN_BUDGET` | Variable | `100000` |
| `MAX_CONCURRENT_EXPERIMENTS` | Variable | `1` |
"""


def _ignore(directory: str, names: list[str]) -> set[str]:
    return {n for n in names if n in SKIP_DIRS or n in SKIP_NAMES or n.startswith(".env.")
            or Path(n).suffix in SKIP_SUFFIXES}


def build() -> Path:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    shutil.copytree(ROOT / "backend", OUT / "backend", ignore=_ignore)
    shutil.copy(ROOT / "docker" / "backend.Dockerfile", OUT / "Dockerfile")
    shutil.copy(ROOT / "LICENSE", OUT / "LICENSE")
    (OUT / "README.md").write_text(SPACE_README, encoding="utf-8")
    (OUT / ".gitignore").write_text(".env\n*.db\n__pycache__/\n", encoding="utf-8")

    leaked = [p for p in OUT.rglob("*") if p.is_file() and (p.name == ".env" or p.suffix in SKIP_SUFFIXES)]
    if leaked:
        sys.exit(f"refusing: unexpected files staged: {leaked}")
    files = sum(1 for p in OUT.rglob("*") if p.is_file())
    print(f"Space staged in {OUT} ({files} files, no secrets)")
    return OUT


def push(space: str) -> None:
    token = os.environ.get("HF_TOKEN")
    if not token:
        sys.exit("Set HF_TOKEN (a Hugging Face *write* token) in your environment to push.")
    user = space.split("/")[0]
    remote = f"https://{user}:{token}@huggingface.co/spaces/{space}"

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=OUT, check=True)

    git("init", "-q", "-b", "main")
    git("add", "-A")
    git("-c", "user.name=ExperimentOS deploy", "-c", "user.email=deploy@experimentos.local",
        "commit", "-q", "-m", "Deploy ExperimentOS API")
    # The Space repo is a deployment target only: its history is replaced on every deploy.
    subprocess.run(["git", "push", "--force", remote, "main"], cwd=OUT, check=True)
    print(f"Pushed. Build logs: https://huggingface.co/spaces/{space}?logs=build")
    print(f"API URL once built: https://{space.replace('/', '-').lower()}.hf.space")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--push", metavar="USER/SPACE", help="push the staged Space to Hugging Face")
    args = ap.parse_args()
    build()
    if args.push:
        push(args.push)
