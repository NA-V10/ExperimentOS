import type { Analysis } from "@/types";
import { HypothesisBadge } from "./Badges";

export function AnalysisPanel({ analysis, onEvidence }: { analysis: Analysis; onEvidence?: (runs: string[]) => void }) {
  const g = analysis.grounding || {};
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <span className="section-title">Hypothesis</span>
        <HypothesisBadge status={analysis.hypothesis_status} large />
        <span className={`text-xs ${analysis.source === "nemotron" ? "text-accent" : "text-muted"}`}>
          {analysis.source === "nemotron" ? "Interpreted by Nemotron" : g.fallback ? "Rule-based fallback" : "Rule-based (offline)"}
        </span>
        {Boolean(g.verified) && (
          <span className="rounded-full bg-good-soft px-2 py-0.5 text-[11px] font-medium text-good">
            ✓ Every number verified against measurements
          </span>
        )}
      </div>
      <p className="text-[15px] leading-relaxed">{analysis.summary}</p>
      {analysis.status_rationale && <p className="text-sm text-ink-2">{analysis.status_rationale}</p>}
      {typeof g.status_adjusted === "string" && (
        <p className="rounded-lg bg-warn-soft px-3 py-2 text-xs text-warn">Statistical guard: {g.status_adjusted}</p>
      )}
      <div>
        <div className="section-title mb-2">Key findings</div>
        <ul className="space-y-2">
          {analysis.key_findings.map((f, i) => (
            <li key={i} className="rounded-lg border border-line p-3 text-sm">
              <p>{f.statement}</p>
              {f.evidence.length > 0 && (
                <div className="mt-2 flex flex-wrap items-center gap-1 text-[11px] text-muted">
                  Evidence:
                  {f.evidence.map((r) => (
                    <button key={r} onClick={() => onEvidence?.(f.evidence)}
                      className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-ink-2 hover:text-info">{r}</button>
                  ))}
                </div>
              )}
            </li>
          ))}
        </ul>
      </div>
      {analysis.conclusion && (
        <div>
          <div className="section-title mb-1">Conclusion</div>
          <p className="text-sm">{analysis.conclusion}</p>
        </div>
      )}
      {analysis.limitations.length > 0 && (
        <div>
          <div className="section-title mb-1">Limitations</div>
          <ul className="list-disc space-y-0.5 pl-5 text-sm text-ink-2">
            {analysis.limitations.map((l, i) => <li key={i}>{l}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}
