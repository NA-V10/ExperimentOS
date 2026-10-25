"use client";

import { useEffect, useState } from "react";
import { DashboardCards, ExperimentTable } from "@/components/Dashboard";
import { api } from "@/lib/api";
import { isActive } from "@/lib/format";
import type { Dashboard, ExperimentSummary } from "@/types";

export default function ExperimentsPage() {
  const [data, setData] = useState<{ items: ExperimentSummary[]; dashboard: Dashboard } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    const load = () =>
      api.listExperiments().then((d) => {
        setData(d);
        if (d.items.some((e) => isActive(e.status))) timer = setTimeout(load, 3000);
      }).catch((e: Error) => setError(e.message));
    load();
    return () => clearTimeout(timer);
  }, []);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Experiments</h1>
      {error && <p className="text-bad">{error}</p>}
      {data && (
        <>
          <DashboardCards d={data.dashboard} />
          <div className="card"><ExperimentTable items={data.items} /></div>
        </>
      )}
    </div>
  );
}
