# Experiment runner image for Nebius AI Cloud Serverless AI Jobs (EXECUTION_MODE=nebius).
# Contains ONLY: Python, the sandbox bootstrap, the experiment SDK and the versioned dataset.
# No API keys, no backend code, no network requirements. Generated code is injected per job
# with `nebius ai job create --inject-file`.
FROM python:3.12-slim
RUN useradd --create-home runner
COPY backend/app/execution/runtime/ /opt/experimentos/runtime/
COPY backend/data/rag_eval.json /opt/experimentos/data/rag_eval.json
RUN mkdir -p /opt/experimentos/job /tmp/experimentos-out && chown -R runner /opt/experimentos/job /tmp/experimentos-out
USER runner
WORKDIR /tmp/experimentos-out
ENTRYPOINT []
CMD ["python", "-I", "-B", "/opt/experimentos/runtime/bootstrap.py", "--help"]
