import Link from "next/link";
import { date, expNumber } from "@/lib/format";
import type { Dashboard as D, ExperimentSummary } from "@/types";
import { HypothesisBadge, StatusBadge } from "./Badges";

export function DashboardCards({ d }: { d: D }) {
  const cards = [
    { label: "Experiments", value: d.experiments },
    { label: "Completed", value: d.completed },
    { label: "Supported", value: d.supported + d.partially_supported, hint: d.partially_supported ? `${d.partially_supported} partially` : undefined },
    { label: "Rejected", value: d.rejected },
    { label: "Inconclusive", value: d.inconclusive },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
      {cards.map((c) => (
        <div key={c.label} className="card px-4 py-3">
          <div className="text-xs text-muted">{c.label}</div>
          <div className="mt-1 text-2xl font-semibold tabular-nums">{c.value}</div>
          {c.hint && <div className="text-[11px] text-muted">{c.hint}</div>}
        </div>
      ))}
    </div>
  );
}

export function ExperimentTable({ items, empty = "No experiments yet." }: { items: ExperimentSummary[]; empty?: string }) {
  if (!items.length) return <p className="px-4 py-6 text-sm text-muted">{empty}</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-line text-left text-xs text-muted">
            <th className="px-4 py-2 font-medium">Experiment</th>
            <th className="px-4 py-2 font-medium">Status</th>
            <th className="px-4 py-2 font-medium">Result</th>
            <th className="hidden px-4 py-2 font-medium md:table-cell">Created</th>
          </tr>
        </thead>
        <tbody>
          {items.map((e) => (
            <tr key={e.id} className="border-b border-line/60 last:border-0 hover:bg-surface-2">
              <td className="px-4 py-2.5">
                <Link href={`/experiments/${e.id}`} className="block">
                  <span className="font-mono text-xs text-muted">{expNumber(e.number)}</span>{" "}
                  <span className="font-medium">{e.title || e.research_question}</span>
                  {e.parent_experiment_id && <span className="ml-2 text-[11px] text-muted">↳ follows {e.parent_experiment_id}</span>}
                  <span className="block max-w-xl truncate text-xs text-ink-2">{e.research_question}</span>
                </Link>
              </td>
              <td className="px-4 py-2.5"><StatusBadge status={e.status} /></td>
              <td className="px-4 py-2.5"><HypothesisBadge status={e.hypothesis_status} /></td>
              <td className="hidden px-4 py-2.5 text-xs text-ink-2 md:table-cell">{date(e.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
