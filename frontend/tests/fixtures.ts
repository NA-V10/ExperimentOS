import type { AgentEvent, StatisticsReport } from "@/types";

let id = 0;
export const ev = (p: Partial<AgentEvent>): AgentEvent => ({
  id: ++id, experiment_id: "exp_001", event_type: "log", message: "", stage: null, tool: null, data: {},
  timestamp: "2026-10-03T08:31:02.000Z", ...p,
});

export const stats: StatisticsReport = {
  baseline_run_id: "k3",
  runs: [
    { run_id: "k10", label: "k=10", is_baseline: false, configuration: { retrieval_k: 10, retriever: "bm25" }, n: 40,
      accuracy: 0.825, accuracy_ci95: [0.68, 0.91], retrieval_recall: 0.975, context_tokens: 390, est_llm_latency_ms: 227, latency_ms: 0.5 },
    { run_id: "k3", label: "k=3", is_baseline: true, configuration: { retrieval_k: 3, retriever: "bm25" }, n: 40,
      accuracy: 0.7, accuracy_ci95: [0.55, 0.82], retrieval_recall: 0.85, context_tokens: 117, est_llm_latency_ms: 194, latency_ms: 0.2 },
  ],
  comparisons: [{ run_id: "k10", baseline_run_id: "k3", absolute_diff_pp: 12.5, relative_change_pct: 17.9,
    diff_ci95: [2.5, 22.5], mcnemar_p: 0.021, wins: 6, losses: 1, significant: true }],
  best_run_id: "k10", accuracy_mean: 0.7625, accuracy_median: 0.7625, accuracy_std: 0.088,
  ordered_variable: "retrieval_k", trend: [{ from_run: "k3", to_run: "k10", from_value: 3, to_value: 10, delta_pp: 12.5 }],
  peak_run_id: "k10", diminishing_returns: false, monotonic: "increasing",
  facts: ["k3 (baseline): accuracy 70.0%", "k10 vs baseline k3: +12.5 pp accuracy"],
};
