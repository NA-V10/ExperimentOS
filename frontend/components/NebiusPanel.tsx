import type { AgentEvent, ExperimentState } from "@/types";
import { llmCalls } from "@/lib/timeline";

function Flow({ steps, active }: { steps: string[]; active: boolean }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-sm">
      {steps.map((s, i) => (
        <span key={i} className="flex items-center gap-1.5">
          <span className={`rounded-lg border px-2 py-1 ${active ? "border-accent/40 bg-accent-soft" : "border-line bg-surface-2 text-ink-2"}`}>{s}</span>
          {i < steps.length - 1 && <span className="text-muted" aria-hidden="true">→</span>}
        </span>
      ))}
    </div>
  );
}

/** Shows exactly which Nebius / NVIDIA components did the work — derived from real events. */
export function NebiusPanel({ state, events }: { state: ExperimentState; events: AgentEvent[] }) {
  const calls = llmCalls(events);
  const tokens = calls.reduce((n, e) => n + Number(e.data.prompt_tokens || 0) + Number(e.data.completion_tokens || 0), 0);
  const cached = calls.filter((e) => e.data.cached).length;
  const models = [...new Set(calls.map((e) => String(e.data.model)))];
  const tasks = [...new Set(calls.map((e) => String(e.data.task)))];
  const ex = state.execution;
  const nebiusJob = ex.backend === "nebius_job";
  const evals = ex.total_evaluations ?? 0;

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div className="rounded-xl border border-line p-4">
        <div className="section-title mb-2">Reasoning</div>
        {state.llm_mode === "nemotron" ? (
          <>
            <Flow active steps={["Nebius Token Factory", `NVIDIA Nemotron`, "Experiment plan"]} />
            <div className="mt-3 space-y-1 text-xs text-ink-2">
              <div>Models: {models.length ? models.map((m) => <code key={m} className="mr-1.5">{m}</code>) : "—"}</div>
              <div>
                {calls.length - cached} live calls · {tokens.toLocaleString()} tokens
                {cached > 0 && ` · ${cached} replayed from cache (no tokens used)`}
              </div>
              <div className="truncate" title={tasks.join(", ")}>Tasks: {tasks.join(", ") || "—"}</div>
            </div>
          </>
        ) : (
          <>
            <Flow active={false} steps={["Offline templates", "Experiment plan"]} />
            <p className="mt-3 text-xs text-warn">Nemotron not configured — set NEBIUS_API_KEY and NEBIUS_MODEL.</p>
          </>
        )}
      </div>
      <div className="rounded-xl border border-line p-4">
        <div className="section-title mb-2">Execution</div>
        <Flow active={nebiusJob}
          steps={nebiusJob ? ["Nebius AI Cloud", "Serverless Job", `${evals} evaluations`]
            : ["Local sandbox", "Isolated subprocess", `${evals || "—"} evaluations`]} />
        <div className="mt-3 space-y-1 text-xs text-ink-2">
          {ex.job_id && <div>Job: <code>{ex.job_id}</code></div>}
          {ex.sandbox && <div className="truncate" title={ex.sandbox}>{ex.sandbox}</div>}
          <div>
            {ex.duration_s != null ? `${ex.duration_s}s` : "—"} · attempt {ex.attempts || "—"}
            {!nebiusJob && " · set EXECUTION_MODE=nebius for Nebius AI Cloud jobs"}
          </div>
        </div>
      </div>
    </div>
  );
}
