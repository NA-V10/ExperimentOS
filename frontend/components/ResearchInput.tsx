"use client";

import { useState } from "react";

export const FEATURED_QUESTION = "Does increasing the number of retrieved documents improve RAG answer accuracy?";

const EXAMPLES = [
  "Does reranking improve RAG retrieval accuracy?",
  "How does chunk size affect RAG answer accuracy?",
  "Is hybrid retrieval better than BM25 for answer accuracy?",
  "Do long contexts hurt accuracy through lost-in-the-middle effects?",
];

interface Props {
  onSubmit: (question: string, useResearch: boolean) => Promise<void> | void;
  onFeatured: () => Promise<void> | void;
  busy?: boolean;
  error?: string | null;
  tavilyAvailable?: boolean;
}

export function ResearchInput({ onSubmit, onFeatured, busy = false, error, tavilyAvailable = false }: Props) {
  const [question, setQuestion] = useState("");
  const [useResearch, setUseResearch] = useState(true);
  const valid = question.trim().length >= 10;

  return (
    <div className="card p-5 md:p-6">
      <label htmlFor="question" className="section-title">Ask a research question</label>
      <textarea
        id="question"
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && valid && !busy) void onSubmit(question.trim(), useResearch);
        }}
        rows={3}
        placeholder="Does increasing RAG retrieval depth improve answer accuracy?"
        className="mt-2 w-full resize-none rounded-xl border border-line bg-bg px-4 py-3 text-[15px] leading-relaxed outline-none placeholder:text-muted focus:border-accent"
      />
      <div className="mt-2 flex flex-wrap gap-1.5">
        {EXAMPLES.map((ex) => (
          <button key={ex} type="button" onClick={() => setQuestion(ex)}
            className="rounded-full border border-line px-2.5 py-1 text-xs text-ink-2 hover:bg-surface-2">
            {ex}
          </button>
        ))}
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button type="button" disabled={!valid || busy} onClick={() => onSubmit(question.trim(), useResearch)}
          className="rounded-xl bg-accent px-5 py-2.5 text-sm font-semibold text-surface disabled:opacity-40">
          {busy ? "Starting…" : "Run Experiment"}
        </button>
        <button type="button" disabled={busy} onClick={() => onFeatured()}
          className="rounded-xl border border-line px-4 py-2.5 text-sm font-medium hover:bg-surface-2 disabled:opacity-40">
          ▶ Run Featured Experiment
        </button>
        <span className="rounded-md bg-warn-soft px-2 py-0.5 text-[11px] font-semibold tracking-wide text-warn">DEMO DATASET</span>
        <label className="ml-auto flex items-center gap-2 text-xs text-ink-2" title={tavilyAvailable ? "" : "TAVILY_API_KEY not configured"}>
          <input type="checkbox" checked={useResearch && tavilyAvailable} disabled={!tavilyAvailable}
            onChange={(e) => setUseResearch(e.target.checked)} />
          Search existing evidence (Tavily){!tavilyAvailable && " — not configured"}
        </label>
      </div>
      {error && <p role="alert" className="mt-3 rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{error}</p>}
      <p className="mt-3 text-xs text-muted">
        Featured: “{FEATURED_QUESTION}” · rag-eval-v1 · seed 42
      </p>
    </div>
  );
}
