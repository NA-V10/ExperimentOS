import type { ExperimentSummary } from "@/types";

/** Group experiments into research trails: root → follow-up → follow-up … */
export function buildTrails(items: ExperimentSummary[]): ExperimentSummary[][] {
  const byParent = new Map<string, ExperimentSummary[]>();
  for (const e of items) {
    if (e.parent_experiment_id) byParent.set(e.parent_experiment_id, [...(byParent.get(e.parent_experiment_id) ?? []), e]);
  }
  const ids = new Set(items.map((e) => e.id));
  const roots = items.filter((e) => !e.parent_experiment_id || !ids.has(e.parent_experiment_id)).sort((a, b) => a.number - b.number);
  const trails: ExperimentSummary[][] = [];
  const walk = (e: ExperimentSummary, trail: ExperimentSummary[]) => {
    const kids = (byParent.get(e.id) ?? []).sort((a, b) => a.number - b.number);
    if (!kids.length) trails.push([...trail, e]);
    kids.forEach((k) => walk(k, [...trail, e]));
  };
  roots.forEach((r) => walk(r, []));
  return trails;
}
