import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AgentTimeline } from "@/components/AgentTimeline";
import { AnalysisPanel } from "@/components/AnalysisPanel";
import { HypothesisBadge, StatusBadge } from "@/components/Badges";
import { EvidenceTable } from "@/components/EvidencePanel";
import { NextExperiment } from "@/components/NextExperiment";
import { ResearchInput } from "@/components/ResearchInput";
import { chartRows, ResultsChart } from "@/components/ResultsChart";
import { deriveTimeline } from "@/lib/timeline";
import { buildTrails } from "@/lib/trails";
import type { Analysis, ExperimentSummary, NextExperimentProposal } from "@/types";
import { ev, stats } from "./fixtures";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => <a href={href} {...rest}>{children}</a>,
}));

describe("experiment creation", () => {
  it("submits a research question", async () => {
    const onSubmit = vi.fn();
    render(<ResearchInput onSubmit={onSubmit} onFeatured={vi.fn()} />);
    const button = screen.getByRole("button", { name: "Run Experiment" });
    expect(button).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/ask a research question/i), {
      target: { value: "Does increasing RAG retrieval depth improve answer accuracy?" },
    });
    fireEvent.click(button);
    expect(onSubmit).toHaveBeenCalledWith("Does increasing RAG retrieval depth improve answer accuracy?", true);
  });

  it("runs the featured experiment in one click", () => {
    const onFeatured = vi.fn();
    render(<ResearchInput onSubmit={vi.fn()} onFeatured={onFeatured} />);
    fireEvent.click(screen.getByRole("button", { name: /run featured experiment/i }));
    expect(onFeatured).toHaveBeenCalled();
    expect(screen.getByText("DEMO DATASET")).toBeInTheDocument();
  });

  it("shows an error state", () => {
    render(<ResearchInput onSubmit={vi.fn()} onFeatured={vi.fn()} error="Cannot reach the ExperimentOS backend" />);
    expect(screen.getByRole("alert")).toHaveTextContent("Cannot reach the ExperimentOS backend");
  });
});

describe("status display", () => {
  it("derives step states only from real events", () => {
    const events = [
      ev({ event_type: "stage", stage: "understand", data: { state: "completed" }, message: "understood" }),
      ev({ event_type: "tool_call", stage: "hypothesis", tool: "create_hypothesis" }),
      ev({ event_type: "stage", stage: "hypothesis", data: { state: "started" }, message: "Generating hypothesis" }),
    ];
    const steps = deriveTimeline(events, "PLANNING");
    expect(steps.find((s) => s.key === "understand")!.state).toBe("done");
    expect(steps.find((s) => s.key === "hypothesis")!.state).toBe("running");
    expect(steps.find((s) => s.key === "hypothesis")!.tools).toEqual(["create_hypothesis"]);
    expect(steps.find((s) => s.key === "run")!.state).toBe("pending");
  });

  it("marks the running step failed when the experiment fails", () => {
    const events = [ev({ event_type: "stage", stage: "run", data: { state: "started", total: 120 }, message: "Running" }),
      ev({ event_type: "progress", stage: "run", data: { done: 30, total: 120 } })];
    const steps = deriveTimeline(events, "FAILED");
    const run = steps.find((s) => s.key === "run")!;
    expect(run.state).toBe("failed");
    expect(run.label).toBe("Running 120 evaluations");
    expect(run.progress).toEqual({ done: 30, total: 120 });
  });

  it("renders the timeline with progress", () => {
    render(<AgentTimeline status="RUNNING" events={[
      ev({ event_type: "stage", stage: "run", data: { state: "started", total: 120 }, message: "Running" }),
      ev({ event_type: "progress", stage: "run", data: { done: 60, total: 120 } }),
    ]} />);
    expect(screen.getByText("Running 120 evaluations")).toBeInTheDocument();
    expect(screen.getByText("60/120")).toBeInTheDocument();
  });

  it("renders status and hypothesis badges", () => {
    render(<><StatusBadge status="GENERATING_CODE" /><HypothesisBadge status="PARTIALLY_SUPPORTED" /></>);
    expect(screen.getByText("Generating code")).toBeInTheDocument();
    expect(screen.getByText("PARTIALLY SUPPORTED")).toBeInTheDocument();
  });
});

describe("results rendering", () => {
  it("orders chart rows by the independent variable and computes CI offsets", () => {
    const rows = chartRows(stats);
    expect(rows.map((r) => r.run)).toEqual(["k3", "k10"]);
    expect(rows[1]).toMatchObject({ accuracy: 82.5, recall: 97.5, best: true });
    expect(rows[1].ci).toEqual([14.5, 8.5]);
  });

  it("renders the chart container", () => {
    render(<ResultsChart stats={stats} />);
    expect(screen.getByLabelText(/accuracy and retrieval recall/i)).toBeInTheDocument();
  });

  it("renders measured evidence with only the varied parameters", () => {
    render(<EvidenceTable stats={stats} />);
    expect(screen.getByText("82.5%")).toBeInTheDocument();
    expect(screen.getByText("+12.5 pp")).toBeInTheDocument();
    expect(screen.getByText(/0\.021/)).toBeInTheDocument();
    expect(screen.getByText("retrieval_k=10")).toBeInTheDocument(); // retriever is controlled → hidden
    expect(screen.getByText("BASELINE")).toBeInTheDocument();
  });

  it("renders a grounded analysis with evidence links", () => {
    const analysis: Analysis = {
      summary: "Accuracy rose with depth.", hypothesis_status: "SUPPORTED", status_rationale: "significant",
      key_findings: [{ statement: "k10 beat k3.", evidence: ["k3", "k10"] }], evidence: ["k3", "k10"],
      limitations: ["small dataset"], conclusion: "Depth helps.", next_experiment: null,
      grounding: { verified: true }, source: "nemotron",
    };
    const onEvidence = vi.fn();
    render(<AnalysisPanel analysis={analysis} onEvidence={onEvidence} />);
    expect(screen.getByText("SUPPORTED")).toBeInTheDocument();
    expect(screen.getByText(/every number verified/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "k10" }));
    expect(onEvidence).toHaveBeenCalledWith(["k3", "k10"]);
  });
});

describe("next experiment flow", () => {
  const proposal: NextExperimentProposal = {
    title: "Reranking vs retrieval depth", research_question: "Does reranking help?",
    hypothesis: "Reranking 20 chunks to top 5 beats k=10.", rationale: "Recall saturated.",
    varied_parameter: "reranker",
    baseline: { label: "k=10", params: { retrieval_k: 10 } },
    treatment: { label: "k=20 + rerank", params: { retrieval_k: 20, reranker: "cross_lite", rerank_top_n: 5 } },
    configurations: [],
  };

  it("runs the next experiment", async () => {
    const onRun = vi.fn().mockResolvedValue(undefined);
    render(<NextExperiment proposal={proposal} onRun={onRun} />);
    expect(screen.getByText("retrieval_k=20, reranker=cross_lite, rerank_top_n=5")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /run next experiment/i }));
    await waitFor(() => expect(onRun).toHaveBeenCalled());
  });

  it("surfaces errors from starting the next experiment", async () => {
    render(<NextExperiment proposal={proposal} onRun={vi.fn().mockRejectedValue(new Error("backend down"))} />);
    fireEvent.click(screen.getByRole("button", { name: /run next experiment/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("backend down");
  });

  it("opens the existing follow-up instead of launching a duplicate run", () => {
    const child = { id: "exp_002", number: 2, status: "RUNNING" } as ExperimentSummary;
    const onRun = vi.fn();
    render(<NextExperiment proposal={proposal} onRun={onRun} existing={[child]} />);
    expect(screen.queryByRole("button", { name: /run next experiment/i })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /open experiment #002/i })).toHaveAttribute("href", "/experiments/exp_002");
  });

  it("allows a retry when the earlier follow-up failed", () => {
    const failed = { id: "exp_002", number: 2, status: "FAILED" } as ExperimentSummary;
    render(<NextExperiment proposal={proposal} onRun={vi.fn()} existing={[failed]} />);
    expect(screen.getByRole("button", { name: /run next experiment/i })).toBeInTheDocument();
    expect(screen.getByText(/earlier attempt #002/i)).toBeInTheDocument();
  });

  it("builds research trails from parent links", () => {
    const base = { title: "", research_question: "q", hypothesis: null, status: "COMPLETED", hypothesis_status: null,
      created_at: "", updated_at: "", completed_at: null, llm_mode: "offline", execution_mode: "local", featured: false,
      summary: null, code_source: null, next_experiment_title: null, error: null } as const;
    const items: ExperimentSummary[] = [
      { ...base, id: "exp_003", number: 3, parent_experiment_id: "exp_002" },
      { ...base, id: "exp_001", number: 1, parent_experiment_id: null },
      { ...base, id: "exp_002", number: 2, parent_experiment_id: "exp_001" },
      { ...base, id: "exp_004", number: 4, parent_experiment_id: null },
    ];
    expect(buildTrails(items).map((t) => t.map((e) => e.number))).toEqual([[1, 2, 3], [4]]);
  });
});
