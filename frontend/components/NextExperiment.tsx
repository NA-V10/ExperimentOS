"use client";

import Link from "next/link";
import { useState } from "react";
import { paramsLabel, expNumber } from "@/lib/format";
import type { ExperimentSummary, NextExperimentProposal } from "@/types";

interface Props {
  proposal: NextExperimentProposal;
  onRun: () => Promise<void> | void;
  existing?: ExperimentSummary[];
}

export function NextExperiment({ proposal, onRun, existing = [] }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const active = existing.find((c) => c.status !== "FAILED" && c.status !== "CANCELLED");
  const retried = existing.filter((c) => c !== active);
  return (
    <div className="space-y-4">
      <div>
        <div className="text-lg font-semibold">{proposal.title}</div>
        <p className="mt-1 text-sm text-ink-2">{proposal.research_question}</p>
      </div>
      <div>
        <div className="section-title mb-1">Hypothesis</div>
        <p className="text-[15px] leading-relaxed">{proposal.hypothesis}</p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-xl border border-line p-3">
          <div className="section-title">Baseline</div>
          <div className="mt-1 text-sm font-medium">{proposal.baseline.label}</div>
          <div className="mt-0.5 font-mono text-xs text-ink-2">{paramsLabel(proposal.baseline.params)}</div>
        </div>
        <div className="rounded-xl border border-accent/40 bg-accent-soft p-3">
          <div className="section-title">Treatment</div>
          <div className="mt-1 text-sm font-medium">{proposal.treatment.label}</div>
          <div className="mt-0.5 font-mono text-xs text-ink-2">{paramsLabel(proposal.treatment.params)}</div>
        </div>
      </div>
      <p className="text-sm text-ink-2"><span className="font-medium text-ink">Why: </span>{proposal.rationale}</p>
      <div className="flex flex-wrap items-center gap-3">
        {active ? (
          // Guardrail: one follow-up per proposal — open it instead of launching a second paid run.
          <Link href={`/experiments/${active.id}`}
            className="rounded-xl border border-accent px-5 py-2.5 text-sm font-bold tracking-wide text-accent">
            OPEN EXPERIMENT {expNumber(active.number)} →
          </Link>
        ) : (
          <button
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              setError(null);
              try { await onRun(); } catch (e) { setError((e as Error).message); setBusy(false); }
            }}
            className="rounded-xl bg-accent px-5 py-2.5 text-sm font-bold tracking-wide text-surface disabled:opacity-50"
          >
            {busy ? "STARTING…" : "▶ RUN NEXT EXPERIMENT"}
          </button>
        )}
        <span className="text-xs text-muted">{proposal.configurations.length} configurations · varies {proposal.varied_parameter}</span>
        {retried.map((c) => (
          <Link key={c.id} href={`/experiments/${c.id}`} className="text-xs text-muted underline">
            Earlier attempt {expNumber(c.number)} ({c.status.toLowerCase()})
          </Link>
        ))}
      </div>
      {error && <p role="alert" className="text-sm text-bad">{error}</p>}
    </div>
  );
}
