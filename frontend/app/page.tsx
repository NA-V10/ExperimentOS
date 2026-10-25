"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { DashboardCards, ExperimentTable } from "@/components/Dashboard";
import { ResearchInput } from "@/components/ResearchInput";
import { api } from "@/lib/api";
import { useHealth } from "@/lib/hooks";
import type { Dashboard, ExperimentSummary } from "@/types";

const LOOP = ["Question", "Hypothesis", "Experiment", "Code", "Execution", "Measurements", "Evidence", "Conclusion", "Next experiment"];

export default function ResearchLab() {
  const router = useRouter();
  const { health } = useHealth();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<{ items: ExperimentSummary[]; dashboard: Dashboard } | null>(null);

  useEffect(() => {
    api.listExperiments().then(setData).catch(() => setData(null));
  }, []);

  const start = async (fn: () => Promise<ExperimentSummary>) => {
    setBusy(true);
    setError(null);
    try {
      const exp = await fn();
      router.push(`/experiments/${exp.id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  return (
    <div className="space-y-8">
      <header>
        <p className="section-title">Autonomous AI Experimentation Laboratory</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight md:text-4xl">
          AI that doesn&apos;t just answer questions.<br className="hidden md:block" />{" "}
          <span className="text-accent">It runs experiments to find out.</span>
        </h1>
        <p className="mt-3 max-w-2xl text-ink-2">
          ExperimentOS turns an AI/ML research question into a falsifiable hypothesis, a controlled experiment and
          executable code — runs it, measures the evidence, and uses it to decide what to test next.
        </p>
      </header>

      <div className="grid gap-3 md:grid-cols-[1fr_2.2fr]">
        <div className="card p-4">
          <div className="section-title">Typical assistant</div>
          <div className="mt-2 flex flex-wrap items-center gap-1.5 text-sm text-ink-2">
            <span className="rounded-md bg-surface-2 px-2 py-1">Question</span>→
            <span className="rounded-md bg-surface-2 px-2 py-1">LLM</span>→
            <span className="rounded-md bg-surface-2 px-2 py-1">Answer</span>
          </div>
        </div>
        <div className="card border-accent/40 p-4">
          <div className="section-title text-accent">ExperimentOS</div>
          <div className="mt-2 flex flex-wrap items-center gap-1.5 text-sm">
            {LOOP.map((s, i) => (
              <span key={s} className="flex items-center gap-1.5">
                <span className="rounded-md bg-accent-soft px-2 py-1">{s}</span>
                {i < LOOP.length - 1 ? <span className="text-muted">→</span> : <span className="text-accent">↺</span>}
              </span>
            ))}
          </div>
        </div>
      </div>

      <ResearchInput
        busy={busy}
        error={error}
        tavilyAvailable={health?.tavily === "configured"}
        onSubmit={(q, r) => start(() => api.createExperiment(q, r))}
        onFeatured={() => start(api.runFeatured)}
      />

      {data && (
        <>
          <DashboardCards d={data.dashboard} />
          <section className="card">
            <div className="flex items-center justify-between px-4 pt-4">
              <h2 className="font-semibold">Recent experiments</h2>
              <Link href="/experiments" className="text-sm text-info">View all →</Link>
            </div>
            <ExperimentTable items={data.items.slice(0, 6)} empty="No experiments yet — run the featured experiment to start." />
          </section>
        </>
      )}
    </div>
  );
}
