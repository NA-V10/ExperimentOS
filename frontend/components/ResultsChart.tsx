"use client";

import {
  Bar, BarChart, CartesianGrid, ErrorBar, LabelList, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import type { StatisticsReport } from "@/types";

interface Row {
  run: string;
  accuracy: number;
  recall: number;
  ci: [number, number];
  baseline: boolean;
  best: boolean;
  n: number;
  tokens: number;
}

export function chartRows(stats: StatisticsReport): Row[] {
  const order = stats.ordered_variable
    ? [...stats.runs].sort((a, b) => Number(a.configuration[stats.ordered_variable!]) - Number(b.configuration[stats.ordered_variable!]))
    : stats.runs;
  return order.map((r) => ({
    run: r.run_id,
    accuracy: +(r.accuracy * 100).toFixed(1),
    recall: +(r.retrieval_recall * 100).toFixed(1),
    // ErrorBar takes [below, above] offsets from the value.
    ci: [+((r.accuracy - r.accuracy_ci95[0]) * 100).toFixed(1), +((r.accuracy_ci95[1] - r.accuracy) * 100).toFixed(1)],
    baseline: r.is_baseline,
    best: r.run_id === stats.best_run_id,
    n: r.n,
    tokens: r.context_tokens,
  }));
}

function TooltipBody({ active, payload }: { active?: boolean; payload?: { payload: Row }[] }) {
  if (!active || !payload?.length) return null;
  const r = payload[0].payload;
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-lg">
      <div className="mb-1 font-mono font-semibold text-ink">{r.run}{r.baseline ? " · baseline" : ""}{r.best ? " · best" : ""}</div>
      <div className="flex items-center gap-2 text-ink-2">
        <span className="h-2 w-2 rounded-sm" style={{ background: "var(--series-1)" }} />
        Accuracy <span className="ml-auto font-mono text-ink">{r.accuracy}%</span>
      </div>
      <div className="text-[11px] text-muted">95% CI {(r.accuracy - r.ci[0]).toFixed(1)}–{(r.accuracy + r.ci[1]).toFixed(1)}%</div>
      <div className="mt-1 flex items-center gap-2 text-ink-2">
        <span className="h-2 w-2 rounded-sm" style={{ background: "var(--series-2)" }} />
        Retrieval recall <span className="ml-auto font-mono text-ink">{r.recall}%</span>
      </div>
      <div className="mt-1 text-[11px] text-muted">{r.n} questions · {r.tokens.toFixed(0)} context tokens</div>
    </div>
  );
}

/** Accuracy (with 95% Wilson CI) and retrieval recall per run — one shared 0–100% axis. */
export function ResultsChart({ stats }: { stats: StatisticsReport }) {
  const rows = chartRows(stats);
  return (
    <figure aria-label="Accuracy and retrieval recall by configuration">
      <div className="h-72 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} margin={{ top: 22, right: 8, left: -12, bottom: 0 }} barGap={2} barCategoryGap="28%">
            <CartesianGrid vertical={false} stroke="var(--grid)" />
            <XAxis dataKey="run" tickLine={false} axisLine={{ stroke: "var(--border)" }}
              tick={{ fill: "var(--text-2)", fontSize: 11, fontFamily: "var(--font-mono)" }}
              tickFormatter={(v: string) => (rows.find((r) => r.run === v)?.baseline ? `${v} (base)` : v)} />
            <YAxis domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} tickLine={false} axisLine={false}
              tick={{ fill: "var(--muted)", fontSize: 11 }} tickFormatter={(v: number) => `${v}%`} />
            <Tooltip content={<TooltipBody />} cursor={{ fill: "var(--surface-2)" }} />
            <Legend iconType="square" iconSize={9} wrapperStyle={{ fontSize: 12, color: "var(--text-2)" }} />
            <Bar dataKey="accuracy" name="Accuracy (95% CI)" fill="var(--series-1)" radius={[4, 4, 0, 0]} isAnimationActive={false}>
              <ErrorBar dataKey="ci" width={6} strokeWidth={1.5} stroke="var(--text-2)" direction="y" />
              <LabelList dataKey="accuracy" position="top" offset={10}
                content={(p) => {
                  const { x, y, width, value, index } = p as { x: number; y: number; width: number; value: number; index: number };
                  const r = rows[index];
                  if (!r || !(r.best || r.baseline)) return null; // selective direct labels
                  return (
                    <text x={x + width / 2} y={y - 12} textAnchor="middle" fontSize={11} fontWeight={600} fill="var(--text)">
                      {value}%
                    </text>
                  );
                }} />
            </Bar>
            <Bar dataKey="recall" name="Retrieval recall" fill="var(--series-2)" radius={[4, 4, 0, 0]} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <figcaption className="mt-1 text-xs text-muted">
        Measured on {rows[0]?.n ?? 0} questions per run. Labels mark the baseline and the best run; hover any bar for details.
      </figcaption>
    </figure>
  );
}
