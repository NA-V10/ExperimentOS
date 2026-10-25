"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { HypothesisBadge, StatusBadge } from "@/components/Badges";
import { api } from "@/lib/api";
import { expNumber } from "@/lib/format";
import { buildTrails } from "@/lib/trails";
import type { ExperimentSummary } from "@/types";

export default function HistoryPage() {
  const [items, setItems] = useState<ExperimentSummary[] | null>(null);
  useEffect(() => { api.listExperiments().then((d) => setItems(d.items)).catch(() => setItems([])); }, []);
  const trails = items ? buildTrails(items) : [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Research History</h1>
        <p className="mt-1 text-sm text-ink-2">Each trail is a chain of experiments where the evidence of one designed the next.</p>
      </div>
      {items && !trails.length && <p className="text-sm text-muted">No experiments yet.</p>}
      {trails.map((trail) => (
        <div key={trail.map((t) => t.id).join("-")} className="card p-5">
          <ol className="relative space-y-4 border-l border-line pl-6">
            {trail.map((e, i) => (
              <li key={e.id} className="relative">
                <span className={`absolute -left-[31px] top-1 grid h-4 w-4 place-items-center rounded-full border-2 border-surface ${
                  e.status === "COMPLETED" ? "bg-good" : e.status === "FAILED" ? "bg-bad" : "bg-info"}`} />
                <Link href={`/experiments/${e.id}`} className="block rounded-lg p-1 hover:bg-surface-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-xs text-muted">Experiment {expNumber(e.number)}</span>
                    <span className="font-medium">{e.title || e.research_question}</span>
                    <StatusBadge status={e.status} />
                    <HypothesisBadge status={e.hypothesis_status} />
                  </div>
                  {e.summary && <p className="mt-1 text-sm text-ink-2">{e.summary}</p>}
                  {i === trail.length - 1 && e.next_experiment_title && (
                    <p className="mt-1 text-xs text-accent">Proposed next: {e.next_experiment_title} (planned)</p>
                  )}
                </Link>
                {i < trail.length - 1 && <div className="mt-1 pl-1 text-[11px] text-muted">↓ evidence → next experiment</div>}
              </li>
            ))}
          </ol>
        </div>
      ))}
    </div>
  );
}
