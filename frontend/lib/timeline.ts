import type { AgentEvent, ExperimentStatus } from "@/types";

export type StepState = "pending" | "running" | "done" | "skipped" | "failed";

export interface TimelineStep {
  key: string;
  label: string;
  state: StepState;
  detail: string;
  tools: string[];
  progress?: { done: number; total: number };
}

export const STEPS: { key: string; label: string }[] = [
  { key: "understand", label: "Understanding question" },
  { key: "research", label: "Searching existing evidence" },
  { key: "hypothesis", label: "Generating hypothesis" },
  { key: "design", label: "Designing experiment" },
  { key: "validate", label: "Validating experiment" },
  { key: "codegen", label: "Generating code" },
  { key: "submit", label: "Submitting execution job" },
  { key: "run", label: "Running evaluations" },
  { key: "analyze", label: "Analyzing results" },
  { key: "next", label: "Generating next experiment" },
];

/** Derive step states purely from real backend events (never simulated). */
export function deriveTimeline(events: AgentEvent[], status: ExperimentStatus): TimelineStep[] {
  const steps = new Map<string, TimelineStep>(
    STEPS.map((s) => [s.key, { ...s, state: "pending" as StepState, detail: "", tools: [] }]),
  );
  for (const e of events) {
    const step = e.stage ? steps.get(e.stage) : undefined;
    if (!step) continue;
    if (e.event_type === "stage") {
      const st = String(e.data.state ?? "");
      step.state = st === "started" ? "running" : st === "completed" ? "done" : st === "skipped" ? "skipped"
        : st === "failed" ? "failed" : step.state;
      step.detail = e.message;
      if (e.stage === "run" && st === "started" && typeof e.data.total === "number") {
        step.label = `Running ${e.data.total} evaluations`;
        step.progress = { done: 0, total: e.data.total };
      }
    } else if (e.event_type === "tool_call" && e.tool && !step.tools.includes(e.tool)) {
      step.tools.push(e.tool);
    } else if (e.event_type === "progress" && typeof e.data.done === "number") {
      step.progress = { done: e.data.done as number, total: (e.data.total as number) || step.progress?.total || 0 };
    }
  }
  if (status === "FAILED" || status === "CANCELLED") {
    for (const s of steps.values()) if (s.state === "running") s.state = "failed";
  }
  return [...steps.values()];
}

export function toolCalls(events: AgentEvent[]): AgentEvent[] {
  return events.filter((e) => e.event_type === "tool_call");
}

export function llmCalls(events: AgentEvent[]): AgentEvent[] {
  return events.filter((e) => e.event_type === "llm_call");
}
