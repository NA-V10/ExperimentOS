"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { paramsLabel, pct, signed } from "@/lib/format";
import type { ExperimentDetail, Params, StatisticsReport } from "@/types";
import { CodeViewer } from "./CodeViewer";
import { Drawer, JsonBlock } from "./Drawer";

type View = "raw" | "code" | "config" | null;

export function EvidenceTable({ stats, highlight }: { stats: StatisticsReport; highlight?: string[] }) {
  const cmp = new Map(stats.comparisons.map((c) => [c.run_id, c]));
  // Show only the parameters that actually vary between runs (the rest are controlled).
  const keys = Object.keys(stats.runs[0]?.configuration ?? {}).filter(
    (k) => new Set(stats.runs.map((r) => JSON.stringify(r.configuration[k]))).size > 1,
  );
  const varied = (cfg: Params) => Object.fromEntries(keys.map((k) => [k, cfg[k]])) as Params;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm" aria-label="Measured evidence per run">
        <thead>
          <tr className="border-b border-line text-left text-xs text-muted">
            <th className="py-2 pr-3 font-medium">Run</th>
            <th className="py-2 pr-3 font-medium">Configuration</th>
            <th className="py-2 pr-3 text-right font-medium">Accuracy</th>
            <th className="py-2 pr-3 text-right font-medium">95% CI</th>
            <th className="py-2 pr-3 text-right font-medium">Recall</th>
            <th className="py-2 pr-3 text-right font-medium">Context tok.</th>
            <th className="py-2 pr-3 text-right font-medium">Δ vs baseline</th>
            <th className="py-2 text-right font-medium">McNemar p</th>
          </tr>
        </thead>
        <tbody>
          {stats.runs.map((r) => {
            const c = cmp.get(r.run_id);
            const hl = highlight?.includes(r.run_id);
            return (
              <tr key={r.run_id} id={`run-${r.run_id}`}
                className={`border-b border-line/60 last:border-0 ${hl ? "bg-info-soft" : ""}`}>
                <td className="py-2 pr-3 font-mono text-xs">
                  {r.run_id}
                  {r.is_baseline && <span className="ml-1.5 rounded bg-surface-2 px-1 py-0.5 text-[10px] font-semibold text-ink-2">BASELINE</span>}
                  {r.run_id === stats.best_run_id && <span className="ml-1.5 rounded bg-good-soft px-1 py-0.5 text-[10px] font-semibold text-good">BEST</span>}
                </td>
                <td className="py-2 pr-3 font-mono text-xs text-ink-2">{paramsLabel(varied(r.configuration))}</td>
                <td className="py-2 pr-3 text-right font-mono font-semibold">{pct(r.accuracy)}</td>
                <td className="py-2 pr-3 text-right font-mono text-xs text-ink-2">{pct(r.accuracy_ci95[0], 0)}–{pct(r.accuracy_ci95[1], 0)}</td>
                <td className="py-2 pr-3 text-right font-mono">{pct(r.retrieval_recall)}</td>
                <td className="py-2 pr-3 text-right font-mono text-ink-2">{r.context_tokens.toFixed(0)}</td>
                <td className="py-2 pr-3 text-right font-mono">
                  {c ? <>{signed(c.absolute_diff_pp, " pp")}<span className="block text-[10px] text-muted">{signed(c.relative_change_pct, "%")} rel.</span></> : "—"}
                </td>
                <td className="py-2 text-right font-mono text-xs">
                  {c ? <span className={c.significant ? "font-semibold text-good" : "text-ink-2"}>
                    {c.mcnemar_p?.toFixed(3)}{c.significant ? " ✓" : ""}
                  </span> : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function EvidencePanel({ exp, highlight }: { exp: ExperimentDetail; highlight?: string[] }) {
  const [view, setView] = useState<View>(null);
  const [raw, setRaw] = useState<unknown>(null);
  const stats = exp.state.statistics;
  if (!stats) return null;

  const openRaw = async () => {
    setView("raw");
    if (!raw) setRaw(await api.getResults(exp.id).catch((e: Error) => ({ error: e.message })));
  };

  return (
    <div>
      <EvidenceTable stats={stats} highlight={highlight} />
      <div className="mt-3 space-y-1 text-xs text-ink-2">
        {stats.facts.map((f, i) => <p key={i}><span className="font-mono text-muted">[{i + 1}]</span> {f}</p>)}
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        <button onClick={openRaw} className="rounded-lg border border-line px-3 py-1.5 text-xs font-medium hover:bg-surface-2">View raw results</button>
        <button onClick={() => setView("code")} className="rounded-lg border border-line px-3 py-1.5 text-xs font-medium hover:bg-surface-2">View generated code</button>
        <button onClick={() => setView("config")} className="rounded-lg border border-line px-3 py-1.5 text-xs font-medium hover:bg-surface-2">View experiment configuration</button>
      </div>
      <Drawer title="Raw results (per-question records)" open={view === "raw"} onClose={() => setView(null)}>
        {raw ? <JsonBlock value={raw} /> : <p className="text-sm text-muted">Loading…</p>}
      </Drawer>
      <Drawer title="Generated experiment code" open={view === "code"} onClose={() => setView(null)}>
        {exp.state.generated_code && <CodeViewer code={exp.state.generated_code} source={exp.state.code_source} />}
      </Drawer>
      <Drawer title="Experiment configuration" open={view === "config"} onClose={() => setView(null)}>
        <JsonBlock value={{ plan: exp.state.experiment_plan, validation: exp.state.validation_result,
          code_validation: exp.state.code_validation, execution: exp.state.execution }} />
      </Drawer>
    </div>
  );
}
