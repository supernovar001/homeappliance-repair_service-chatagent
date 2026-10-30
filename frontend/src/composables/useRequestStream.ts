import { onBeforeUnmount, ref } from "vue";
import { get, type RequestState } from "../api";

// 답변 작업의 진행 단계를 SSE로 받습니다.
// 끊기면 브라우저가 Last-Event-ID로 다시 연결하고, 다시 연결되지 않으면 3초마다 상태를 조회합니다.
export const STAGES = [
  { key: "scope_check", label: "상담 범위 확인" },
  { key: "retrieving", label: "설명서 검색" },
  { key: "generating", label: "답변 작성" },
  { key: "verifying", label: "안전·인용 검사" },
];
export const STAGE_LABELS: Record<string, string> = { ...Object.fromEntries(STAGES.map((s) => [s.key, s.label])), revising: "답변 보완" };

export interface StreamHandlers { onDone: () => void; onError: (message: string) => void }

export function useRequestStream() {
  const stage = ref<string | null>(null);
  const seen = ref<string[]>([]);
  let source: EventSource | null = null;
  let poll: number | undefined;
  let failures = 0;

  function stop() {
    source?.close();
    source = null;
    window.clearInterval(poll);
    poll = undefined;
  }

  function startPolling(id: string, h: StreamHandlers) {
    if (poll) return;
    poll = window.setInterval(async () => {
      try {
        const r = await get<RequestState>(`/api/requests/${id}`);
        if (r.stage) markStage(r.stage);
        if (r.status === "succeeded") { stop(); h.onDone(); }
        else if (r.status === "failed" || r.status === "interrupted") { stop(); h.onError("답변을 만들지 못했습니다. 다시 시도해 주세요."); }
      } catch { /* 다음 주기에 다시 조회합니다. */ }
    }, 3000);
  }

  function markStage(s: string) {
    stage.value = s;
    if (!seen.value.includes(s)) seen.value = [...seen.value, s];
  }

  function watch(id: string, h: StreamHandlers) {
    stop();
    stage.value = null;
    seen.value = [];
    failures = 0;
    source = new EventSource(`/api/requests/${id}/events`);
    source.addEventListener("stage", (e) => { failures = 0; markStage(JSON.parse((e as MessageEvent).data).stage); });
    source.addEventListener("done", () => { stop(); h.onDone(); });
    source.addEventListener("error", (e) => {
      // 서버가 보낸 error 이벤트(작업 실패)에는 data가 있고, 연결 오류에는 없습니다.
      const data = (e as MessageEvent).data;
      if (data) { stop(); h.onError(JSON.parse(data).message); return; }
      failures += 1;
      if (source?.readyState === EventSource.CLOSED || failures >= 3) { source?.close(); source = null; startPolling(id, h); }
    });
  }

  onBeforeUnmount(stop);
  return { stage, seen, watch, stop };
}
