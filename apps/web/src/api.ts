export type Template = "corrected" | "overeager";
export type Execution = {
  state: string;
  output: Record<string, string | number>;
  evidence: Record<string, { rule_path: string; source_fields: string[] }>;
  reviews: { code: string; reason: string }[];
  fault: string | null;
  rounding_applied: boolean;
};
export type Example = {
  case_id: string;
  supplier: string;
  origin: string;
  split: string;
  rationale: string;
  source: Record<string, string>;
  expected: {
    kind: string;
    unit_price?: string;
    price_basis?: string;
    pack_size?: number;
    code?: string;
  };
};
export type Correction = {
  id: string;
  case_id: string;
  revision: number;
  unit_price: string;
  price_basis: string;
  pack_size: number | null;
  reason: string;
  created_at: string;
  author: string;
};
export type Metrics = {
  total: number;
  correct: number;
  correct_covered: number;
  covered: number;
  critical: number;
  faulted: number;
};
export type Outcome = {
  case_id: string;
  origin: string;
  supplier: string;
  verdict: string;
  actual: string;
  expected: string;
  detail: string;
};
export type Evaluation = {
  id: string;
  created_at: string;
  template: Template;
  correction_id: string | null;
  artifact_digest: string;
  fixture_digest: string;
  procedure_digest: string;
  decision: {
    passed: boolean;
    verdict: string;
    new_critical_cases: string[];
    criteria: {
      code: string;
      description: string;
      passed: boolean;
      detail: string;
    }[];
    holdout_comparison: {
      candidate_fixed: number;
      candidate_broke: number;
      p_value: number;
      sample_size: number;
    };
  };
  runs: Record<string, { metrics: Metrics; outcomes: Outcome[] }>;
  groups: Record<string, Record<string, Metrics>>;
  executions: Record<string, { original: Execution; candidate: Execution }>;
  limitations: string[];
};
export type Workspace = {
  suppliers: Record<string, { currency: string; locale: string }>;
  engine: string;
  fixture_digest: string;
  cases: Example[];
  procedures: Record<
    string,
    { name: string; description: string; digest: string; ast: unknown }
  >;
  corrections: Correction[];
  history: {
    id: string;
    template: Template;
    verdict: string;
    created_at: string;
    correction_id: string | null;
  }[];
};
export async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch("/api" + path, {
    method: body === undefined ? "GET" : "POST",
    headers: {
      "Content-Type": "application/json",
      "X-SkillFoundry-Client": "workbench",
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const data = await response
      .json()
      .catch(() => ({ detail: response.statusText }));
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : JSON.stringify(data.detail),
    );
  }
  return response.json();
}
export function isCorrect(verdict: string) {
  return verdict === "correct_value" || verdict === "correct_review";
}
export function percent(count: number, total: number) {
  return total ? `${((count / total) * 100).toFixed(1)}%` : "Not measured";
}
