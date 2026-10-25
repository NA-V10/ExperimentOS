import type { AgentEvent, ExperimentStatus } from "@/types";
import { deriveTimeline, type StepState } from "@/lib/timeline";

const MARK: Record<StepState, { icon: string; cls: string }> = {
  done: { icon: "✓", cls: "text-good" },
  running: { icon: "⟳", cls: "text-info spin inline-block" },
  pending: { icon: "○", cls: "text-muted" },
  skipped: { icon: "–", cls: "text-muted" },
  failed: { icon: "✕", cls: "text-bad" },
};

export function AgentTimeline({ events, status }: { events: AgentEvent[]; status: ExperimentStatus }) {
  const steps = deriveTimeline(events, status);
  return (
    <ol className="space-y-1" aria-label="Agent activity">
      {steps.map((s) => (
        <li key={s.key} data-state={s.state}
          className={`rounded-lg px-3 py-2 ${s.state === "running" ? "bg-info-soft" : ""}`}>
          <div className="flex items-start gap-3">
            <span className={`w-4 text-center font-mono text-sm leading-6 ${MARK[s.state].cls}`} aria-label={s.state}>
              {MARK[s.state].icon}
            </span>
            <div className="min-w-0 flex-1">
              <div className={`text-sm leading-6 ${s.state === "pending" ? "text-muted" : "font-medium"}`}>{s.label}</div>
              {s.detail && s.state !== "pending" && (
                <div className="truncate text-xs text-ink-2" title={s.detail}>{s.detail}</div>
              )}
              {s.progress && s.state !== "pending" && (
                <div className="mt-1.5 flex items-center gap-2">
                  <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-2">
                    <div className="h-full rounded-full bg-info transition-all"
                      style={{ width: `${s.progress.total ? (100 * s.progress.done) / s.progress.total : 0}%` }} />
                  </div>
                  <span className="font-mono text-[11px] text-ink-2">{s.progress.done}/{s.progress.total}</span>
                </div>
              )}
              {s.tools.length > 0 && (
                <div className="mt-1 flex flex-wrap gap-1">
                  {s.tools.map((t) => (
                    <span key={t} className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-[10.5px] text-ink-2">🔧 {t}</span>
                  ))}
                </div>
              )}
            </div>
          </div>
        </li>
      ))}
    </ol>
  );
}
