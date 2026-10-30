// 백엔드 API 호출. 쿠키 세션을 쓰고, 상태를 바꾸는 요청에는 CSRF 토큰을 붙입니다.

export type Route = "자가 점검 우선" | "서비스 기사 점검 권장" | "추가 확인 필요" | "상담 범위 외";

export interface Me { id: string; email: string; name: string; picture: string; is_admin: boolean; csrf_token: string }
export interface SupportedModel { id: string; series: string; washer_model: string; dryer_model: string; manual_id: string }
export interface Product {
  id: string; nickname: string; model_code: string | null; created_at: string; supported_model: SupportedModel;
  conversation_count: number; memory_count: number; draft_memory_count: number;
}
export interface AnswerResult {
  route: Route; reason: string; scope: string | null; symptom: string; error_code: string | null;
  evidence_pages: number[]; evidence_basis: string; evidence_texts: Record<string, string[]>;
  retrieved_pages: number[]; revision_failed: boolean; safety_notes_added: boolean; duration_ms: number;
}
export interface AppliedMemory { memory_id: string | null; version: number; deleted: boolean; symptom?: string; action?: string; outcome?: string }
export interface Message {
  id: string; role: "user" | "assistant"; kind: "question" | "checklist_report" | "answer"; content: string;
  result: AnswerResult | null; created_at: string; bookmarked: boolean; applied_memories: AppliedMemory[];
}
export interface ChecklistItem {
  id: string; message_id: string; key: string; title: string; detail: string; pages: number[];
  kind: "self_check" | "contact_service"; enabled: boolean; status: string; outcome: string; inherited: boolean;
}
export interface Memory {
  id: string; symptom: string; action: string; outcome: string; evidence: string; status: "draft" | "confirmed";
  version: number; source_conversation_id: string | null; confirmed_at: string | null; updated_at: string; selected?: boolean;
}
export interface RequestState {
  id: string; status: "queued" | "running" | "succeeded" | "failed" | "interrupted"; stage: string | null;
  error_type: string | null; attempt: number; user_message_id: string; assistant_message_id: string | null;
}
export interface ConversationSummary { id: string; title: string; product_id: string; product_nickname: string; created_at: string; last_message_at: string }
export interface Conversation extends ConversationSummary {
  product: { id: string; nickname: string; supported_model_id: string };
  messages: Message[]; checklist: ChecklistItem[]; memories: Memory[]; will_apply: string[];
  source_memory_count: number; request: RequestState | null;
}

export const MANUAL_ID = "MFL71831423";
export const CHECK_STATUSES = ["미확인", "확인 완료", "수행 어려움", "해당 없음"];
export const CHECK_OUTCOMES = ["결과 불명", "이상 없음", "이상 발견", "해결됨", "해결되지 않음"];

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

let csrfToken = "";
export function setCsrf(token: string) { csrfToken = token; }

export async function api<T>(method: string, url: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") headers["X-CSRF-Token"] = csrfToken;
  let res: Response;
  try {
    res = await fetch(url, { method, headers, credentials: "same-origin", body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new ApiError(0, "서버에 연결하지 못했습니다. 네트워크를 확인해 주세요.");
  }
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = typeof data.detail === "string" ? data.detail : "요청을 처리하지 못했습니다.";
    throw new ApiError(res.status, detail);
  }
  return data as T;
}

export const get = <T>(url: string) => api<T>("GET", url);
export const post = <T>(url: string, body?: unknown) => api<T>("POST", url, body ?? {});
export const patch = <T>(url: string, body: unknown) => api<T>("PATCH", url, body);
export const put = <T>(url: string, body: unknown) => api<T>("PUT", url, body);
export const del = <T>(url: string) => api<T>("DELETE", url);

export function pageUrl(page: number) { return `/api/manuals/${MANUAL_ID}/pages/${page}`; }
export function newRequestId() { return `web-${crypto.randomUUID()}`; }
