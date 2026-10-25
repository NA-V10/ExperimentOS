import type { ExperimentPlan as Plan, Hypothesis, ValidationCheck } from "@/types";
import { paramsLabel } from "@/lib/format";
import { Chip } from "./Badges";

export function HypothesisCard({ hypothesis }: { hypothesis: Hypothesis }) {
  return (
    <div>
      <p className="text-[17px] leading-relaxed">{hypothesis.statement}</p>
      <div className="mt-3 flex flex-wrap gap-2 text-xs">
        <Chip>IV · <span className="ml-1 font-mono">{hypothesis.independent_variable}</span></Chip>
        <Chip>DV · <span className="ml-1 font-mono">{hypothesis.dependent_variable}</span></Chip>
        <Chip>expected · {hypothesis.expected_direction.replace("_", "-")}</Chip>
      </div>
    </div>
  );
}

export function ValidationChecks({ checks }: { checks: ValidationCheck[] }) {
  return (
    <ul className="grid gap-1.5 sm:grid-cols-2">
      {checks.map((c) => (
        <li key={c.id} className="flex items-start gap-2 text-sm">
          <span className={c.passed ? "text-good" : "text-bad"} aria-label={c.passed ? "passed" : "failed"}>
            {c.passed ? "✓" : "✕"}
          </span>
          <span>
            <span className="font-medium">{c.id}. {c.name}</span>
            <span className="block text-xs text-ink-2">{c.detail}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

export function ExperimentPlan({ plan }: { plan: Plan }) {
  return (
    <div className="space-y-5">
      <p className="text-sm text-ink-2">{plan.objective}</p>
      <div className="grid gap-4 md:grid-cols-3">
        <div>
          <div className="section-title">Independent variable</div>
          {plan.independent_variables.map((v) => (
            <div key={v.name} className="mt-1.5">
              <span className="font-mono text-sm">{v.name}</span>
              <div className="mt-1 flex flex-wrap gap-1">
                {v.values.map((x, i) => <Chip key={i} mono>{x === null ? "none" : String(x)}</Chip>)}
              </div>
            </div>
          ))}
        </div>
        <div>
          <div className="section-title">Dependent variables</div>
          <div className="mt-1.5 flex flex-wrap gap-1">
            {plan.dependent_variables.map((d) => <Chip key={d} mono>{d}</Chip>)}
          </div>
          <div className="section-title mt-3">Dataset · Seed</div>
          <div className="mt-1 text-sm"><span className="font-mono">{plan.dataset.id}</span> · seed {plan.seed}</div>
        </div>
        <div>
          <div className="section-title">Controlled variables</div>
          <ul className="mt-1.5 space-y-0.5 text-xs text-ink-2">
            {plan.control_variables.slice(0, 10).map((c) => <li key={c} className="font-mono">{c}</li>)}
          </ul>
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs text-muted">
              <th className="py-2 pr-3 font-medium">Run</th>
              <th className="py-2 pr-3 font-medium">Configuration</th>
              <th className="py-2 font-medium">Parameters</th>
            </tr>
          </thead>
          <tbody>
            {plan.configurations.map((c) => (
              <tr key={c.run_id} className="border-b border-line/60 last:border-0">
                <td className="py-2 pr-3 font-mono text-xs">{c.run_id}</td>
                <td className="py-2 pr-3">
                  {c.label} {c.is_baseline && <span className="ml-1 rounded bg-surface-2 px-1.5 py-0.5 text-[10px] font-semibold text-ink-2">BASELINE</span>}
                </td>
                <td className="py-2 font-mono text-xs text-ink-2">{paramsLabel(c.params)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div>
        <div className="section-title">Success criteria</div>
        <p className="mt-1 text-sm text-ink-2">{plan.success_criteria}</p>
      </div>
    </div>
  );
}
