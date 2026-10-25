"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { AgentTimeline } from "@/components/AgentTimeline";
import { AnalysisPanel } from "@/components/AnalysisPanel";
import { StatusBadge } from "@/components/Badges";
import { CodeViewer } from "@/components/CodeViewer";
import { EvidenceGraph } from "@/components/EvidenceGraph";
import { EvidencePanel } from "@/components/EvidencePanel";
import { ExecutionLog } from "@/components/ExecutionLog";
import { ExperimentPlan, HypothesisCard, ValidationChecks } from "@/components/ExperimentPlan";
import { NebiusPanel } from "@/components/NebiusPanel";
import { NextExperiment } from "@/components/NextExperiment";
import { ResultsChart } from "@/components/ResultsChart";
import { api } from "@/lib/api";
import { expNumber, isActive } from "@/lib/format";
import { useExperiment } from "@/lib/hooks";

function Section({ title, children, aside }: { title: string; children: React.ReactNode; aside?: React.ReactNode }) {
  return (
    <section className="card p-5">
      <div className="mb-4 flex items-center justify-between gap-3 border-b border-line pb-2">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-ink-2">{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

function Pending({ children }: { children: React.ReactNode }) {
  return <p className="text-sm text-muted">{children}</p>;
}

export default function ExperimentPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { exp, events, error } = useExperiment(id);
  const [highlight, setHighlight] = useState<string[]>([]);
  const [showCode, setShowCode] = useState(false);

  if (error && !exp) return <div className="card p-6 text-bad">{error}</div>;
  if (!exp) return <div className="card p-6 text-muted">Loading experiment…</div>;

  const s = exp.state;
  const active = isActive(exp.status);
  const progress = s.execution.total_evaluations
    ? { done: s.execution.completed_evaluations, total: s.execution.total_evaluations } : null;
  const liveProgress = [...events].reverse().find((e) => e.event_type === "progress");
  const done = liveProgress ? Number(liveProgress.data.done) : progress?.done ?? 0;
  const allChecks = [...(s.validation_result?.checks ?? []), ...(s.code_validation?.checks ?? [])];

  return (
    <div className="space-y-5">
      <header className="space-y-2">
        <div className="flex flex-wrap items-center gap-3">
          <span className="font-mono text-sm text-muted">Experiment {expNumber(exp.number)}</span>
          <StatusBadge status={exp.status} />
          {exp.featured && <span className="rounded-md bg-warn-soft px-2 py-0.5 text-[11px] font-semibold text-warn">DEMO DATASET</span>}
          {s.llm_mode === "offline" && <span className="rounded-md bg-surface-2 px-2 py-0.5 text-[11px] text-ink-2">offline reasoning</span>}
          {active && (
            <button onClick={() => api.cancel(exp.id)} className="ml-auto rounded-lg border border-line px-3 py-1 text-xs hover:bg-surface-2">
              Cancel
            </button>
          )}
        </div>
        <div className="section-title">Research question</div>
        <h1 className="text-2xl font-semibold tracking-tight">{exp.research_question}</h1>
        {exp.parent && (
          <p className="text-sm text-ink-2">
            ↳ Follows <Link className="text-info underline" href={`/experiments/${exp.parent.id}`}>
              Experiment {expNumber(exp.parent.number)} · {exp.parent.title}</Link> — designed from its evidence
          </p>
        )}
        <p className="text-xs text-muted">Seed: {s.experiment_plan?.seed ?? 42} · Dataset version: rag-eval-v1</p>
      </header>

      {exp.status === "FAILED" && (
        <div role="alert" className="card border-bad/40 bg-bad-soft p-4 text-sm text-bad">
          <strong>Experiment failed.</strong> {exp.error}
        </div>
      )}

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="min-w-0 space-y-5">
          {s.research_context?.searched && (
            <Section title="Existing evidence · Tavily">
              {s.research_context.known_findings.length > 0 && (
                <ul className="list-disc space-y-1 pl-5 text-sm">{s.research_context.known_findings.map((f, i) => <li key={i}>{f}</li>)}</ul>
              )}
              {s.research_context.research_gap && <p className="mt-3 text-sm"><span className="font-medium">Research gap: </span>{s.research_context.research_gap}</p>}
              <ul className="mt-3 space-y-1 text-xs">
                {s.research_context.sources.map((src) => (
                  <li key={src.url}><a href={src.url} target="_blank" rel="noreferrer" className="text-info underline">{src.title}</a></li>
                ))}
              </ul>
            </Section>
          )}

          <Section title="Hypothesis">
            {s.hypothesis ? <HypothesisCard hypothesis={s.hypothesis} /> : <Pending>Forming a falsifiable hypothesis…</Pending>}
          </Section>

          <Section title="Experiment design">
            {s.experiment_plan ? (
              <>
                <ExperimentPlan plan={s.experiment_plan} />
                {allChecks.length > 0 && (
                  <div className="mt-5 border-t border-line pt-4">
                    <div className="section-title mb-2">Validation ({allChecks.filter((c) => c.passed).length}/{allChecks.length} checks passed)</div>
                    <ValidationChecks checks={allChecks} />
                  </div>
                )}
              </>
            ) : <Pending>Designing a controlled experiment…</Pending>}
          </Section>

          <Section title="Nebius × NVIDIA">
            <NebiusPanel state={s} events={events} />
          </Section>

          <Section title="Generated code"
            aside={s.generated_code && (
              <button onClick={() => setShowCode((v) => !v)} className="text-xs text-info">{showCode ? "Hide" : "Show code"}</button>
            )}>
            {s.generated_code ? (
              showCode ? <CodeViewer code={s.generated_code} source={s.code_source} /> : (
                <p className="text-sm text-ink-2">
                  {s.generated_code.split("\n").length} lines · {s.code_source === "nemotron" ? "generated by Nemotron" : "template generator"} ·
                  AST-validated (allow-listed imports only) · executed in an isolated sandbox
                </p>
              )
            ) : <Pending>Waiting for the validated plan…</Pending>}
          </Section>

          <Section title="Execution">
            {progress ? (
              <div>
                <div className="flex items-center justify-between text-sm">
                  <span>{s.execution.backend === "nebius_job" ? "Nebius Serverless Job" : "Local sandbox"} · attempt {s.execution.attempts}</span>
                  <span className="font-mono">{done}/{progress.total} evaluations</span>
                </div>
                <div className="mt-2 h-2 overflow-hidden rounded-full bg-surface-2">
                  <div className="h-full rounded-full bg-info transition-all" style={{ width: `${(100 * done) / progress.total}%` }} />
                </div>
                {s.execution.error && <p className="mt-2 text-xs text-bad">Last error: {s.execution.error}</p>}
                <div className="mt-3 flex flex-wrap gap-2 text-xs">
                  {exp.runs.map((r) => (
                    <span key={r.run_id} className={`rounded-md border px-2 py-0.5 font-mono ${
                      r.status === "COMPLETED" ? "border-good/40 text-good" : r.status === "RUNNING" ? "border-info/40 text-info" : "border-line text-muted"}`}>
                      {r.status === "COMPLETED" ? "✓" : r.status === "RUNNING" ? "⟳" : "○"} {r.run_id}
                    </span>
                  ))}
                </div>
              </div>
            ) : <Pending>Not submitted yet.</Pending>}
          </Section>

          <Section title="Results">
            {s.statistics ? (
              <div className="space-y-5">
                <ResultsChart stats={s.statistics} />
                <div className="section-title">Evidence</div>
                <EvidencePanel exp={exp} highlight={highlight} />
              </div>
            ) : <Pending>Results appear when measurements are complete.</Pending>}
          </Section>

          <Section title="Analysis">
            {s.analysis ? (
              <AnalysisPanel analysis={s.analysis} onEvidence={(runs) => {
                setHighlight(runs);
                document.getElementById(`run-${runs[0]}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
              }} />
            ) : <Pending>Analysis runs on the measured results.</Pending>}
          </Section>

          <Section title="Evidence graph">
            <EvidenceGraph state={s} />
          </Section>

          <Section title="Next experiment">
            {s.next_experiment ? (
              <NextExperiment
                proposal={s.next_experiment}
                existing={exp.children}
                onRun={async () => {
                  const child = await api.runNext(exp.id);
                  router.push(`/experiments/${child.id}`);
                }}
              />
            ) : <Pending>Proposed once the evidence is analysed.</Pending>}
          </Section>
        </div>

        <aside className="space-y-5 lg:sticky lg:top-6 lg:self-start">
          <Section title="Agent activity">
            <AgentTimeline events={events} status={exp.status} />
          </Section>
        </aside>
      </div>

      <Section title="Execution log">
        <ExecutionLog events={events} />
      </Section>
    </div>
  );
}
