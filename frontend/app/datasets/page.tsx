"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

interface DatasetDetail {
  id: string; name: string; version: string; n_questions: number; n_documents: number; description: string;
  sha256: string; seed: number; decoy_documents: number;
  questions: { id: string; question: string; expected_answer: string; answer_type: string; question_style: string; n_context: number }[];
  sample_record: Record<string, unknown>;
}

export default function DatasetsPage() {
  const [ds, setDs] = useState<DatasetDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.getDataset("rag-eval-v1").then((d) => setDs(d as unknown as DatasetDetail)).catch((e: Error) => setError(e.message));
  }, []);

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">Datasets</h1>
        <span className="rounded-md bg-warn-soft px-2 py-0.5 text-[11px] font-semibold text-warn">DEMO DATASET</span>
      </div>
      {error && <p className="text-bad">{error}</p>}
      {ds && (
        <>
          <div className="card p-5">
            <div className="text-lg font-semibold">{ds.name}</div>
            <p className="mt-1 max-w-3xl text-sm text-ink-2">{ds.description}</p>
            <dl className="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-5">
              {[["Version", ds.version], ["Questions", ds.n_questions], ["Passages", ds.n_documents],
                ["Decoy passages", ds.decoy_documents], ["Seed", ds.seed]].map(([k, v]) => (
                <div key={String(k)}><dt className="text-xs text-muted">{k}</dt><dd className="font-mono">{String(v)}</dd></div>
              ))}
            </dl>
            <p className="mt-3 break-all font-mono text-[11px] text-muted">sha256 {ds.sha256}</p>
            <p className="mt-2 text-xs text-muted">Rebuild byte-identically with <code>python scripts/build_dataset.py</code>.</p>
          </div>
          <div className="card overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-line text-left text-xs text-muted">
                  <th className="px-4 py-2 font-medium">ID</th><th className="px-4 py-2 font-medium">Question</th>
                  <th className="px-4 py-2 font-medium">Expected</th><th className="px-4 py-2 font-medium">Type</th>
                  <th className="px-4 py-2 font-medium">Style</th>
                </tr>
              </thead>
              <tbody>
                {ds.questions.map((q) => (
                  <tr key={q.id} className="border-b border-line/60 last:border-0">
                    <td className="px-4 py-2 font-mono text-xs">{q.id}</td>
                    <td className="px-4 py-2">{q.question}</td>
                    <td className="px-4 py-2 font-mono text-xs">{q.expected_answer}</td>
                    <td className="px-4 py-2 text-xs text-ink-2">{q.answer_type}</td>
                    <td className="px-4 py-2 text-xs text-ink-2">{q.question_style}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
