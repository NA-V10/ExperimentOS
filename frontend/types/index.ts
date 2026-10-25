export type ExperimentStatus =
  | "CREATED" | "PLANNING" | "VALIDATING" | "GENERATING_CODE" | "QUEUED"
  | "RUNNING" | "ANALYZING" | "COMPLETED" | "FAILED" | "CANCELLED";

export type HypothesisStatus = "SUPPORTED" | "PARTIALLY_SUPPORTED" | "REJECTED" | "INCONCLUSIVE";

export type Params = Record<string, string | number | null>;

export interface Hypothesis {
  statement: string;
  independent_variable: string;
  dependent_variable: string;
  expected_direction: string;
  expected_relationship: string;
  rationale?: string;
}

export interface RunConfiguration {
  run_id: string;
  label: string;
  params: Params;
  is_baseline: boolean;
}

export interface ExperimentPlan {
  hypothesis: string;
  objective: string;
  independent_variables: { name: string; description?: string; values: unknown[] }[];
  dependent_variables: string[];
  control_variables: string[];
  baseline: { run_id: string; description: string };
  configurations: RunConfiguration[];
  dataset: { id: string; name: string };
  metrics: { name: string; goal: string; description?: string }[];
  primary_metric: string;
  success_criteria: string;
  estimated_runs: number;
  seed: number;
}

export interface ValidationCheck { id: number; name: string; passed: boolean; detail: string }

export interface RunStatistics {
  run_id: string;
  label: string;
  is_baseline: boolean;
  configuration: Params;
  n: number;
  accuracy: number;
  accuracy_ci95: [number, number];
  retrieval_recall: number;
  context_tokens: number;
  est_llm_latency_ms: number;
  latency_ms: number;
}

export interface Comparison {
  run_id: string;
  baseline_run_id: string;
  absolute_diff_pp: number | null;
  relative_change_pct: number | null;
  diff_ci95: [number, number] | null;
  mcnemar_p: number | null;
  wins: number;
  losses: number;
  significant: boolean;
}

export interface StatisticsReport {
  baseline_run_id: string;
  runs: RunStatistics[];
  comparisons: Comparison[];
  best_run_id: string;
  accuracy_mean: number;
  accuracy_median: number;
  accuracy_std: number;
  ordered_variable: string | null;
  trend: { from_run: string; to_run: string; from_value: unknown; to_value: unknown; delta_pp: number }[];
  peak_run_id: string | null;
  diminishing_returns: boolean;
  monotonic: string;
  facts: string[];
}

export interface NextExperimentProposal {
  title: string;
  research_question: string;
  hypothesis: string;
  rationale: string;
  varied_parameter: string;
  baseline: { label: string; params: Params };
  treatment: { label: string; params: Params };
  configurations: RunConfiguration[];
}

export interface Analysis {
  summary: string;
  hypothesis_status: HypothesisStatus;
  status_rationale: string;
  key_findings: { statement: string; evidence: string[] }[];
  evidence: string[];
  limitations: string[];
  conclusion: string;
  next_experiment: NextExperimentProposal | null;
  grounding: Record<string, unknown>;
  source: "nemotron" | "offline";
}

export interface ResearchContext {
  searched: boolean;
  query: string;
  known_findings: string[];
  assumptions: string[];
  research_gap: string;
  testable_locally: string;
  sources: { title: string; url: string; snippet: string }[];
  note: string;
}

export interface ExecutionInfo {
  backend: "local_sandbox" | "nebius_job" | null;
  job_id: string | null;
  attempts: number;
  duration_s: number | null;
  total_evaluations: number | null;
  completed_evaluations: number;
  sandbox: string;
  error: string | null;
  logs_tail: string[];
}

export interface ExperimentState {
  research_question: string;
  research_context: ResearchContext | null;
  understanding: { experiment_family: string; independent_variable: string; summary: string } | null;
  hypothesis: Hypothesis | null;
  experiment_plan: ExperimentPlan | null;
  validation_result: { checks: ValidationCheck[] } | null;
  code_validation: { checks: ValidationCheck[] } | null;
  generated_code: string | null;
  code_source: "nemotron" | "template" | null;
  execution: ExecutionInfo;
  statistics: StatisticsReport | null;
  analysis: Analysis | null;
  next_experiment: NextExperimentProposal | null;
  seed_proposal: NextExperimentProposal | null;
  error: string | null;
  llm_mode: "nemotron" | "offline";
  models: Record<string, string>;
}

export interface AgentEvent {
  id: number;
  experiment_id: string;
  event_type: "status" | "stage" | "tool_call" | "tool_result" | "llm_call" | "progress" | "log" | "warning" | "error" | "retry";
  message: string;
  stage: string | null;
  tool: string | null;
  data: Record<string, unknown>;
  timestamp: string;
}

export interface ExperimentSummary {
  id: string;
  number: number;
  title: string | null;
  research_question: string;
  hypothesis: string | null;
  status: ExperimentStatus;
  hypothesis_status: HypothesisStatus | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  parent_experiment_id: string | null;
  llm_mode: string;
  execution_mode: string;
  featured: boolean;
  summary: string | null;
  code_source: string | null;
  next_experiment_title: string | null;
  error: string | null;
}

export interface RunRow { run_id: string; label: string; configuration: Params; is_baseline: boolean; status: string }

export interface ExperimentDetail extends ExperimentSummary {
  state: ExperimentState;
  runs: RunRow[];
  results: { run_id: string; configuration: Params; metrics: Record<string, number> }[];
  events: AgentEvent[] | null;
  sources: { title: string; url: string; snippet: string }[];
  children: ExperimentSummary[];
  parent: ExperimentSummary | null;
}

export interface Dashboard {
  experiments: number;
  completed: number;
  running: number;
  failed: number;
  supported: number;
  partially_supported: number;
  rejected: number;
  inconclusive: number;
}

export interface Health {
  status: string;
  nebius: string;
  model: string;
  models: { reasoning: string | null; fast: string | null };
  llm_provider: string;
  llm_mode: "nemotron" | "offline" | "unavailable";
  tavily: string;
  execution: string;
  execution_mode: string;
  execution_detail: string;
  dataset: { id: string; name: string; version: string; n_questions: number; n_documents: number; sha256: string } | null;
  help?: string;
  guardrails?: {
    daily_token_budget: number | null;
    tokens_used_today: number;
    live_calls_today: number;
    tokens_remaining_today: number | null;
    max_calls_per_experiment: number | null;
    max_concurrent_experiments: number | null;
    experiment_rate_limit_per_minute: number | null;
    response_cache: boolean;
    running_experiments: number;
  };
}
