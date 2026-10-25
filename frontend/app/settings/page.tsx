"use client";

import { API_URL } from "@/lib/api";
import { useHealth } from "@/lib/hooks";

function Row({ k, v, ok }: { k: string; v: React.ReactNode; ok?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-line/60 py-2.5 text-sm last:border-0">
      <span className="text-ink-2">{k}</span>
      <span className={`text-right font-mono text-xs ${ok === false ? "text-warn" : ok ? "text-good" : ""}`}>{v}</span>
    </div>
  );
}

export default function SettingsPage() {
  const { health, error } = useHealth();
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
      <p className="text-sm text-ink-2">Configuration is read from environment variables on the backend (see <code>.env.example</code>). Secrets are never sent to the browser.</p>
      {error && <p className="text-bad">{error}</p>}
      {health && (
        <div className="grid gap-5 md:grid-cols-2">
          <div className="card p-5">
            <h2 className="mb-2 font-semibold">Reasoning · Nebius Token Factory</h2>
            <Row k="NEBIUS_API_KEY" v={health.nebius} ok={health.nebius === "configured"} />
            <Row k="NEBIUS_MODEL (reasoning)" v={health.models.reasoning ?? "not set"} ok={!!health.models.reasoning} />
            <Row k="NEBIUS_FAST_MODEL" v={health.models.fast ?? "not set"} ok={!!health.models.fast} />
            <Row k="Mode" v={health.llm_mode} ok={health.llm_mode === "nemotron"} />
            {health.help && <p className="mt-3 rounded-lg bg-warn-soft p-3 text-xs text-warn">{health.help}</p>}
          </div>
          <div className="card p-5">
            <h2 className="mb-2 font-semibold">Execution · Nebius AI Cloud</h2>
            <Row k="EXECUTION_MODE" v={health.execution_mode} />
            <Row k="Status" v={health.execution} ok={health.execution === "ready"} />
            <Row k="Detail" v={health.execution_detail} />
          </div>
          {health.guardrails && (
            <div className="card p-5 md:col-span-2">
              <h2 className="mb-2 font-semibold">Usage guardrails</h2>
              {health.guardrails.daily_token_budget && (
                <div className="mb-3">
                  <div className="flex justify-between text-xs text-ink-2">
                    <span>Nemotron tokens today</span>
                    <span className="font-mono">
                      {health.guardrails.tokens_used_today.toLocaleString()} / {health.guardrails.daily_token_budget.toLocaleString()}
                    </span>
                  </div>
                  <div className="mt-1 h-2 overflow-hidden rounded-full bg-surface-2">
                    <div className={`h-full rounded-full ${health.guardrails.tokens_remaining_today === 0 ? "bg-bad" : "bg-accent"}`}
                      style={{ width: `${Math.min(100, (100 * health.guardrails.tokens_used_today) / health.guardrails.daily_token_budget)}%` }} />
                  </div>
                </div>
              )}
              <Row k="Live Nemotron calls today" v={health.guardrails.live_calls_today} />
              <Row k="LLM_DAILY_TOKEN_BUDGET" v={health.guardrails.daily_token_budget?.toLocaleString() ?? "unlimited"} />
              <Row k="LLM_MAX_CALLS_PER_EXPERIMENT" v={health.guardrails.max_calls_per_experiment ?? "unlimited"} />
              <Row k="MAX_CONCURRENT_EXPERIMENTS" v={health.guardrails.max_concurrent_experiments ?? "unlimited"} />
              <Row k="EXPERIMENT_RATE_LIMIT_PER_MINUTE" v={health.guardrails.experiment_rate_limit_per_minute ?? "unlimited"} />
              <Row k="LLM_CACHE (replay identical requests)" v={health.guardrails.response_cache ? "on" : "off"}
                ok={health.guardrails.response_cache} />
              <p className="mt-2 text-xs text-muted">The budget resets at 00:00 UTC. If it runs out mid-experiment, the run
                finishes on the rule-based path so measurements are never lost.</p>
            </div>
          )}
          <div className="card p-5">
            <h2 className="mb-2 font-semibold">Research discovery · Tavily</h2>
            <Row k="TAVILY_API_KEY" v={health.tavily} ok={health.tavily === "configured"} />
            <p className="mt-2 text-xs text-muted">Optional. Without it the core loop runs unchanged.</p>
          </div>
          <div className="card p-5">
            <h2 className="mb-2 font-semibold">System</h2>
            <Row k="Backend" v={API_URL} />
            <Row k="Dataset" v={health.dataset ? `${health.dataset.id} (${health.dataset.n_questions} q)` : "—"} />
            <Row k="Seed" v="42" />
          </div>
        </div>
      )}
    </div>
  );
}
