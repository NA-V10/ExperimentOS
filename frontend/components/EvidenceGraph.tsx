import type { ExperimentState } from "@/types";
import { hypothesisLabel, pct } from "@/lib/format";

function Node({ kind, children, tone = "default" }: { kind: string; children: React.ReactNode; tone?: "default" | "accent" | "good" }) {
  const t = tone === "accent" ? "border-accent/50 bg-accent-soft" : tone === "good" ? "border-good/40 bg-good-soft" : "border-line bg-surface";
  return (
    <div className={`rounded-xl border px-3 py-2 ${t}`}>
      <div className="text-[10px] font-semibold uppercase tracking-wider text-muted">{kind}</div>
      <div className="mt-0.5 text-sm leading-snug">{children}</div>
    </div>
  );
}

const Arrow = () => <div className="flex justify-center py-1 text-muted" aria-hidden="true">↓</div>;

/** Question → Hypothesis → Experiment → Configurations → Measurement → Finding → Conclusion → Next. */
export function EvidenceGraph({ state }: { state: ExperimentState }) {
  const { hypothesis, experiment_plan: plan, statistics: stats, analysis, next_experiment: next } = state;
  if (!hypothesis || !plan) return <p className="text-sm text-muted">The evidence graph appears once the experiment is designed.</p>;
  const runStats = new Map(stats?.runs.map((r) => [r.run_id, r]) ?? []);
  const iv = plan.independent_variables[0]?.name;
  const peak = stats?.peak_run_id || stats?.best_run_id;
  const pattern = stats
    ? stats.ordered_variable
      ? `${stats.monotonic.replace("_", "-")} trend${stats.diminishing_returns ? " · diminishing returns" : ""}; peak at ${peak}`
      : `best: ${stats.best_run_id}`
    : "awaiting measurements";

  return (
    <div className="mx-auto max-w-2xl" role="img" aria-label="Evidence graph from research question to next experiment">
      <Node kind="Research question">{state.research_question}</Node>
      <Arrow />
      <Node kind="Hypothesis">{hypothesis.statement}</Node>
      <Arrow />
      <Node kind="Experiment">Vary <span className="font-mono">{iv}</span>; measure accuracy · {plan.dataset.id} · seed {plan.seed}</Node>
      <Arrow />
      <div className="text-center text-[10px] font-semibold uppercase tracking-wider text-muted">Configurations → Measurements</div>
      <div className="mt-1 grid gap-2" style={{ gridTemplateColumns: `repeat(${Math.min(plan.configurations.length, 4)}, minmax(0, 1fr))` }}>
        {plan.configurations.map((c) => {
          const r = runStats.get(c.run_id);
          const best = stats?.best_run_id === c.run_id;
          return (
            <div key={c.run_id} className={`rounded-xl border px-2 py-2 text-center ${best ? "border-good/50 bg-good-soft" : "border-line bg-surface"}`}>
              <div className="truncate font-mono text-[11px] text-ink-2" title={c.label}>{c.label}</div>
              <div className="mt-1 font-mono text-base font-semibold">{r ? pct(r.accuracy) : "…"}</div>
              <div className="mx-auto mt-1 h-1 w-full overflow-hidden rounded bg-surface-2">
                <div className="h-full rounded" style={{ width: `${(r?.accuracy ?? 0) * 100}%`, background: "var(--series-1)" }} />
              </div>
              {c.is_baseline && <div className="mt-1 text-[9px] font-semibold text-muted">BASELINE</div>}
            </div>
          );
        })}
      </div>
      <Arrow />
      <Node kind="Finding">{pattern}</Node>
      <Arrow />
      <Node kind="Conclusion" tone={analysis ? "good" : "default"}>
        {analysis ? <><strong>{hypothesisLabel(analysis.hypothesis_status)}</strong> — {analysis.conclusion || analysis.summary}</> : "pending analysis"}
      </Node>
      <Arrow />
      <Node kind="Next experiment" tone="accent">{next ? next.title : "pending"}</Node>
    </div>
  );
}
