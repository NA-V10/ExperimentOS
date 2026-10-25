"use client";

import { useState } from "react";
import { time } from "@/lib/format";
import type { AgentEvent } from "@/types";

const FILTERS = {
  all: () => true,
  agent: (e: AgentEvent) => ["status", "stage", "tool_call", "retry", "warning", "error"].includes(e.event_type),
  nemotron: (e: AgentEvent) => e.event_type === "llm_call",
  execution: (e: AgentEvent) => e.stage === "run" || e.stage === "submit",
} as const;

const COLOR: Partial<Record<AgentEvent["event_type"], string>> = {
  error: "text-bad", warning: "text-warn", retry: "text-warn", llm_call: "text-accent", status: "text-info",
  tool_call: "text-ink",
};

export function ExecutionLog({ events }: { events: AgentEvent[] }) {
  const [filter, setFilter] = useState<keyof typeof FILTERS>("all");
  const shown = events.filter(FILTERS[filter]).filter((e) => e.event_type !== "tool_result");
  return (
    <div>
      <div className="mb-2 flex gap-1" role="tablist">
        {(Object.keys(FILTERS) as (keyof typeof FILTERS)[]).map((f) => (
          <button key={f} role="tab" aria-selected={filter === f} onClick={() => setFilter(f)}
            className={`rounded-md px-2 py-1 text-xs capitalize ${filter === f ? "bg-surface-2 font-medium" : "text-ink-2"}`}>
            {f}
          </button>
        ))}
      </div>
      <div className="max-h-80 overflow-auto rounded-xl border border-line bg-bg p-3 font-mono text-[11.5px] leading-relaxed">
        {shown.length === 0 && <div className="text-muted">No events yet.</div>}
        {shown.map((e) => (
          <div key={e.id} className="flex gap-3">
            <span className="shrink-0 text-muted">{time(e.timestamp)}</span>
            <span className={COLOR[e.event_type] ?? "text-ink-2"}>
              {e.event_type === "tool_call" ? `🔧 ${e.tool} — ` : ""}{e.message}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
