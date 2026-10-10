/** Client for the governed write APIs (identity, adjustments, corrections, exceptions). Same-origin through the dev proxy; the session is an HttpOnly cookie the browser
 *  sends by itself, and every state-changing call carries X-FPA-Request: 1 (the server also checks the Origin). No token or password is ever kept in JavaScript. */
export type Area = "auth" | "adjustments" | "corrections" | "inbox";
const BASE: Record<Area, string> = { auth: "/auth-api", adjustments: "/adjustments-api", corrections: "/corrections-api", inbox: "/inbox-api" };

export class ControlApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

type Params = Record<string, string | number | boolean | undefined | null>;

export async function call<T>(area: Area, method: "GET" | "POST" | "PUT", path: string, opts: { params?: Params; body?: unknown } = {}): Promise<T> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(opts.params ?? {})) if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  const headers: Record<string, string> = { Accept: "application/json" };
  if (method !== "GET") headers["X-FPA-Request"] = "1";
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(`${BASE[area]}${path}${qs.size ? `?${qs}` : ""}`, { method, headers, credentials: "same-origin", body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined });
  if (!res.ok) {
    let msg = res.status === 401 ? "Sign in required." : `The request failed (${res.status}).`;
    try {
      const j = (await res.json()) as { detail?: unknown };
      if (typeof j.detail === "string") msg = j.detail;
    } catch {
      /* keep the generic message */
    }
    throw new ControlApiError(msg, res.status);
  }
  return ((await res.json()) as { data: T }).data;
}

export interface Me { user_id: string; email: string; display_name: string; role: Role; must_change_password: boolean }
export type Role = "viewer" | "fpa_manager" | "finance_reviewer" | "controller" | "admin";
export const MAKERS: Role[] = ["fpa_manager", "controller", "admin"];
export const CHECKERS: Role[] = ["fpa_manager", "finance_reviewer", "controller", "admin"];

export const auth = {
  me: () => call<Me>("auth", "GET", "/me"),
  login: (email: string, password: string) => call<Me>("auth", "POST", "/login", { body: { email, password } }),
  logout: () => call<{ signed_out: boolean }>("auth", "POST", "/logout"),
  changePassword: (current_password: string, new_password: string) => call<{ changed: boolean }>("auth", "POST", "/change-password", { body: { current_password, new_password } }),
  assignable: () => call<{ user_id: string; email: string; display_name: string; role: Role }[]>("auth", "GET", "/assignable"),
  users: () => call<AdminUser[]>("auth", "GET", "/admin/users"),
  createUser: (email: string, display_name: string, role: Role) => call<{ user_id: string; email: string; role: Role; temporary_password: string }>("auth", "POST", "/admin/users", { body: { email, display_name, role } }),
  setRole: (id: string, role: Role) => call<{ ok: boolean }>("auth", "POST", `/admin/users/${id}/role`, { body: { role } }),
  setActive: (id: string, active: boolean) => call<{ ok: boolean }>("auth", "POST", `/admin/users/${id}/${active ? "activate" : "deactivate"}`),
  resetPassword: (id: string) => call<{ user_id: string; email: string; temporary_password: string }>("auth", "POST", `/admin/users/${id}/reset-password`),
  unlock: (id: string) => call<{ ok: boolean }>("auth", "POST", `/admin/users/${id}/unlock`),
};

export interface AdminUser { user_id: string; email: string; display_name: string; role: Role; active: boolean; must_change_password: boolean; locked_until: string | null; last_login_at: string | null }

/* ---------------- adjustments ---------------- */
export type AdjStatus = "DRAFT" | "REVIEW" | "APPROVED" | "ACTIVE" | "REJECTED" | "WITHDRAWN" | "REVERSAL_REQUESTED" | "REVERSED";
export interface Adjustment {
  adjustment_id: string; month: string; entity: string; management_line: string; location_type: string; location_code: string | null; adjustment_type: string; basis_type: "FIXED" | "RATE" | "MANUAL";
  amount_rupees: string; amount_cr: string; effect: "COST" | "INCOME"; rate: string | null; rate_metric: string | null; metric_snapshot: { value_rupees?: string; partial_month?: boolean; as_of?: string } | null;
  supporting_reference: string; narrative: string; linked_policy: string | null; status: AdjStatus; provisional: boolean; counts_in_management_total: boolean; template_id: string | null;
  created_by: string; created_at: string; approved_by: string | null; approved_at: string | null; activated_at: string | null;
}
export interface AdjInput {
  month: string; entity: string; management_line: string; location_type: string; adjustment_type: string; basis_type: string; effect: string; amount_rupees?: string; rate?: string; rate_metric?: string;
  supporting_reference: string; narrative: string; linked_policy?: string; location_code?: string;
}
export interface HistoryEvent { seq: number; event_type: string; from_status: string | null; to_status: string; comment: string | null; at: string; actor_email?: string | null; actor?: string | null; actor_name?: string | null; closure_reason?: string | null; new_owner?: string | null; new_due_date?: string | null; new_next_action?: string | null }
export interface ImpactCell { before: string; after: string; change: string }
export interface Impact { month: string; entity: string; line: string; location_type: string; amount_cr: string; already_in_management_total: boolean; views: Record<string, Record<string, ImpactCell>>; note: string }
export interface TemplateRow { template_id: string; name: string; entity: string; management_line: string; location_type: string; adjustment_type: string; basis_type: string; fixed_amount_rupees: string | null; rate: string | null; rate_metric: string | null; effect: "COST" | "INCOME"; start_month: string; end_month: string | null; status: string; last_generated_month: string | null }
export interface CalendarRow { template_id: string; name: string; entity: string; line: string; status: string; cells: Record<string, { state: string; adjustment_id: string | null; amount_cr: string | null }> }
export interface Calendar { months: string[]; rows: CalendarRow[]; legend: string[] }

export const adjustments = {
  list: (p: { month?: string; status?: string; limit?: number } = {}) => call<{ total: number; items: Adjustment[] }>("adjustments", "GET", "", { params: p }),
  one: (id: string) => call<Adjustment>("adjustments", "GET", `/${id}`),
  history: (id: string) => call<HistoryEvent[]>("adjustments", "GET", `/${id}/history`),
  create: (b: AdjInput) => call<Adjustment>("adjustments", "POST", "", { body: b }),
  update: (id: string, b: AdjInput) => call<Adjustment>("adjustments", "PUT", `/${id}`, { body: b }),
  preview: (b: AdjInput) => call<Impact>("adjustments", "POST", "/preview", { body: b }),
  previewSaved: (id: string) => call<Impact>("adjustments", "GET", `/${id}/preview`),
  act: (id: string, action: string, comment?: string) => call<Adjustment>("adjustments", "POST", `/${id}/${action}`, { body: { comment } }),
  templates: () => call<TemplateRow[]>("adjustments", "GET", "/templates"),
  createTemplate: (b: AdjInput & { name: string; start_month: string; end_month?: string }) => call<TemplateRow>("adjustments", "POST", "/templates", { body: b }),
  templateAction: (id: string, action: string) => call<TemplateRow>("adjustments", "POST", `/templates/${id}/${action}`),
  generate: (month: string) => call<{ month: string; created: { template: string; adjustment_id: string; provisional: boolean }[]; skipped: { template: string; reason: string }[] }>("adjustments", "POST", `/templates/generate/${month}`),
  calendar: (from_month: string, to_month: string) => call<Calendar>("adjustments", "GET", "/calendar", { params: { from_month, to_month } }),
};

/* ---------------- corrections ---------------- */
export type CorStatus = "DRAFT" | "SUBMITTED" | "APPROVED" | "ACTIVE" | "REJECTED" | "WITHDRAWN" | "REVERSAL_REQUESTED" | "REVERSED" | "SOURCE_REVIEW_REQUIRED" | "SUPERSEDED_BY_SOURCE";
export interface CorLine { line_id: string; source_line_key: string; voucher_key: string; ledger_key: string; site_code: string | null; original_group: string; corrected_group: string | null; original_month: string; corrected_month: string | null; source_amount_cr: string; source_state: string }
export interface Correction {
  request_id: string; scope_type: string; correction_type: string; source_entity: string; status: CorStatus; reason_code: string; reason_text: string; evidence_reference: string; requested_by: string; requested_at: string;
  approved_at: string | null; line_count: number; source_total_cr: string; counts_in_management_total: boolean; lines?: CorLine[];
}
export interface SourceLine { cost_tag_key: number; fingerprint?: string; ledger: string; entry_date: string; site_code: number | null; amount_cr: string; management_group: string | null; month: string | null; correctable: boolean; not_correctable_reason: string | null; active_correction: { request_id: string; corrected_group: string | null; corrected_month: string | null } | null }
export interface CorPreview { lines: number; stores: number; source_total_cr: string; by_group: Record<string, string>; by_month: Record<string, string>; net_by_group_cr: string; net_by_month_cr: string; note: string }
export interface CorCreate { source_entity: string; scope: "LINE" | "VOUCHER" | "BULK"; line_keys?: number[]; voucher?: string; corrected_group?: string; corrected_month?: string; reason_code: string; reason_text: string; evidence_reference: string }

export const corrections = {
  list: (p: { status?: string } = {}) => call<{ total: number; counts: Record<string, number>; items: Correction[] }>("corrections", "GET", "", { params: p }),
  one: (id: string) => call<Correction>("corrections", "GET", `/${id}`),
  history: (id: string) => call<HistoryEvent[]>("corrections", "GET", `/${id}/history`),
  preview: (id: string) => call<CorPreview>("corrections", "GET", `/${id}/preview`),
  sourceLines: (entity: string, voucher: string) => call<{ voucher: string; entity: string; lines: SourceLine[]; groups: string[]; read_at?: string }>("corrections", "GET", "/source-lines", { params: { entity, voucher } }),
  groups: () => call<{ group: string; line: string }[]>("corrections", "GET", "/groups"),
  create: (b: CorCreate) => call<Correction>("corrections", "POST", "", { body: b }),
  previewNew: (b: CorCreate) => call<CorPreview>("corrections", "POST", "/preview", { body: b }),
  act: (id: string, action: string, comment?: string) => call<Correction>("corrections", "POST", `/${id}/${action}`, { body: { comment } }),
  sourceCheck: () => call<{ checked: number; changed: string[]; superseded: string[] }>("corrections", "POST", "/source-check"),
};

/* ---------------- exceptions ---------------- */
export interface Case {
  case_id: string; exception_type: string; domain: string; entity: string | null; site_code: string | null; metric_id: string | null; period: string | null; subject_key: string | null; title: string;
  recurrence_of_case_id: string | null; recurrence_no: number; final_score: string; band: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW"; escalated: boolean; evidence: Record<string, unknown>; drill_link: string | null;
  status: "OPEN" | "ACKNOWLEDGED" | "RESOLVED" | "CLOSED"; owner_user_id: string | null; due_date: string | null; next_action: string | null; closure_reason: string | null; first_detected_at: string; last_detected_at: string;
  detection_count: number; overdue: boolean; recurring: boolean; lineage?: { case_id: string; status: string; closed_at: string | null; closure_reason: string | null; recurrence_no: number }[];
}
export interface CaseList { total: number; shown: number; bands: Record<string, number>; unowned: number; overdue: number; items: Case[]; score_note: string }

export const inbox = {
  list: (p: { status?: string; domain?: string; band?: string; search?: string; mine?: boolean; top?: number } = {}) => call<CaseList>("inbox", "GET", "", { params: p }),
  one: (id: string) => call<Case>("inbox", "GET", `/${id}`),
  history: (id: string) => call<HistoryEvent[]>("inbox", "GET", `/${id}/history`),
  thresholds: () => call<{ version: string; calibration_status: string; thresholds: Record<string, unknown> }>("inbox", "GET", "/thresholds"),
  detect: () => call<{ created: number; recurred: number; candidates: number; errors: string[] }>("inbox", "POST", "/detect"),
  assign: (id: string, owner_user_id: string, due_date?: string, next_action?: string) => call<Case>("inbox", "POST", `/${id}/assign`, { body: { owner_user_id, due_date, next_action } }),
  act: (id: string, action: string, comment?: string, closure_reason?: string) => call<Case>("inbox", "POST", `/${id}/${action}`, { body: { comment, closure_reason } }),
  comment: (id: string, comment: string) => call<Case>("inbox", "POST", `/${id}/comment`, { body: { comment } }),
  nextAction: (id: string, text: string) => call<Case>("inbox", "POST", `/${id}/next-action`, { body: { text } }),
};
