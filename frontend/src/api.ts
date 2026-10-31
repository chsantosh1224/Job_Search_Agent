export type ApplicationStatus =
  | "new"
  | "shortlisted"
  | "applied"
  | "interviewing"
  | "offer"
  | "rejected"
  | "archived";

export type View = "matches" | "other" | "tracked" | "filtered";
export type Region = "worldwide" | "india" | "unspecified";

export interface JobFilters {
  view: View;
  q?: string;
  tier?: number | null;
  salaryMinUsd?: number | null;
  salaryMaxUsd?: number | null;
  includeUnknownSalary?: boolean;
  regions?: Region[];
}

export interface Me {
  id: number;
  email: string;
  name: string;
  about: string;
  min_salary_usd: number | null;
  is_admin: boolean;
  consented: boolean;
  resume: { filename: string; uploaded_at: string; ready: boolean; ranked: boolean } | null;
}

export interface AdminUser {
  id: number;
  email: string;
  name: string;
  is_admin: boolean;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
  has_resume: boolean;
  matches: number;
  calls_today: number;
  ranked_today: number;
  briefs_today: number;
}

export interface AdminOverview {
  calls_today: number;
  daily_cap: number;
  user_rank_limit: number;
  user_brief_limit: number;
  users: AdminUser[];
}

export interface JobItem {
  id: number;
  title: string;
  company: string | null;
  source: string;
  url: string;
  location: string | null;
  remote_type: string;
  india_eligible: boolean | null;
  salary_min_usd: number | null;
  salary_max_usd: number | null;
  posted_at: string | null;
  filter_reason: string | null;
  tier: number | null;
  fit_score: number | null;
  ranked: boolean;
  has_brief: boolean;
  status: ApplicationStatus | null;
}

export interface Brief {
  company_summary?: string;
  stage_and_funding?: string;
  people?: { name: string; role?: string | null }[];
  lead_project?: string;
  why_lead_project?: string;
  talking_points?: string[];
  verify_before_reaching_out?: string[];
}

export interface JobDetail extends JobItem {
  description: string;
  salary_raw: string | null;
  company_website: string | null;
  company_description: string | null;
  yc_batch: string | null;
  extra: Record<string, unknown>;
  similarity: number | null;
  reasons: string[];
  gaps: string[];
  model: string | null;
  brief: Brief | null;
  brief_model: string | null;
  notes: string;
  label: Label | null;
}

export interface Label {
  is_good_fit: boolean;
  expected_tier: number | null;
  notes: string;
}

export interface QueueItem {
  id: number;
  title: string;
  company: string | null;
  location: string | null;
  url: string;
  salary_max_lpa: number | null;
  snippet: string;
}

export interface Mistake {
  job_id: number;
  title: string;
  company: string | null;
  kind: string;
  tier: number | null;
  fit_score: number | null;
  expected_tier: number | null;
}

export interface RankingMetrics {
  labeled: number;
  labeled_good: number;
  evaluated: number;
  not_ranked_yet: number;
  threshold: number;
  confusion: { tp: number; fp: number; fn: number; tn: number };
  precision: number | null;
  recall: number | null;
  f1: number | null;
  accuracy: number | null;
  precision_at_5: number | null;
  precision_at_10: number | null;
  tier_accuracy: number | null;
  tier_within_one: number | null;
  auc_llm: number | null;
  auc_similarity: number | null;
  mistakes: Mistake[];
}

export interface BriefEvalDetail {
  job_id: number;
  title: string;
  company: string | null;
  writer_model: string | null;
  judge_model: string;
  faithfulness: number | null;
  claims: number;
  unsupported: string[];
  specificity: number;
  usefulness: number;
  comment: string;
  people_not_in_source: string[];
  lead_project_in_resume: boolean;
}

export interface EvalRunSummary {
  id: number;
  kind: "ranking" | "briefs";
  created_at: string;
  metrics: Record<string, unknown>;
  details?: BriefEvalDetail[];
}

export interface EvalsOverview {
  label_goal: number;
  ranking: RankingMetrics;
  latest_briefs: EvalRunSummary | null;
  history: EvalRunSummary[];
}

export interface Run {
  id: number;
  trigger: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  stats: Record<string, unknown>;
  user_id: number | null;
}

export interface Summary {
  jobs_total: number;
  jobs_passed: number;
  briefs: number;
  tiers: Record<string, number>;
  applications: Partial<Record<ApplicationStatus, number>>;
  resume: string | null;
  daily_run_time_ist: string;
  runs: Run[];
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  // JSON bodies are strings; file uploads (FormData) set their own multipart content type.
  const headers = new Headers(init?.headers);
  if (typeof init?.body === "string") headers.set("Content-Type", "application/json");
  const response = await fetch(path, { ...init, credentials: "same-origin", headers });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = typeof body.detail === "string" ? body.detail : response.statusText;
    throw new ApiError(response.status, detail);
  }
  return response.status === 204 ? (undefined as T) : response.json();
}

export const googleLoginUrl = (next?: string) =>
  `/api/auth/google/login${next ? `?next=${encodeURIComponent(next)}` : ""}`;

export const api = {
  authConfig: () => request<{ google: boolean; dev_login: boolean }>("/api/auth/config"),
  devLogin: (email: string) =>
    request<void>("/api/auth/dev-login", { method: "POST", body: JSON.stringify({ email }) }),
  logout: () => request<void>("/api/auth/logout", { method: "POST" }),
  me: () => request<Me>("/api/me"),
  updateMe: (data: { name: string; about: string; min_salary_usd: number | null }) =>
    request<Me>("/api/me", { method: "PUT", body: JSON.stringify(data) }),
  consent: () => request<Me>("/api/me/consent", { method: "POST" }),
  uploadResume: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Me>("/api/me/resume", { method: "POST", body: form });
  },
  deleteMe: () => request<void>("/api/me", { method: "DELETE" }),
  jobs: (f: JobFilters) => {
    const query = new URLSearchParams({ view: f.view });
    if (f.q) query.set("q", f.q);
    if (f.tier) query.set("tier", String(f.tier));
    if (f.salaryMinUsd != null) query.set("salary_min_usd", String(f.salaryMinUsd));
    if (f.salaryMaxUsd != null) query.set("salary_max_usd", String(f.salaryMaxUsd));
    if (f.includeUnknownSalary === false) query.set("include_unknown_salary", "false");
    for (const region of f.regions ?? []) query.append("region", region);
    return request<JobItem[]>(`/api/jobs?${query}`);
  },
  adminUsers: () => request<AdminOverview>("/api/admin/users"),
  setUserActive: (id: number, is_active: boolean) =>
    request<{ id: number }>(`/api/admin/users/${id}`, {
      method: "PUT",
      body: JSON.stringify({ is_active }),
    }),
  job: (id: number) => request<JobDetail>(`/api/jobs/${id}`),
  updateApplication: (id: number, status: ApplicationStatus, notes: string) =>
    request<JobDetail>(`/api/jobs/${id}/application`, {
      method: "PUT",
      body: JSON.stringify({ status, notes }),
    }),
  summary: () => request<Summary>("/api/summary"),
  runNow: () => request<{ id: number; status: string }>("/api/runs", { method: "POST" }),
  evals: () => request<EvalsOverview>("/api/evals"),
  labelQueue: () => request<QueueItem[]>("/api/evals/queue"),
  setLabel: (id: number, label: Label) =>
    request<Label>(`/api/jobs/${id}/label`, { method: "PUT", body: JSON.stringify(label) }),
  deleteLabel: (id: number) => request<void>(`/api/jobs/${id}/label`, { method: "DELETE" }),
  snapshotRankingEval: () => request<EvalRunSummary>("/api/evals/ranking", { method: "POST" }),
};
