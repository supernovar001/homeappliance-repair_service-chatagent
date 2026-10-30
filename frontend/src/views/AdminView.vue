<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { get, type Message } from "../api";
import Icon from "../components/Icon.vue";
import RouteBadge from "../components/RouteBadge.vue";

interface Period { conversations: number; answers: number; errors: number; median_ms: number | null; p95_ms: number | null }
interface Stats {
  from: string; to: string; days: number; has_data: boolean; current: Period; previous: Period;
  daily_answers: { date: string; count: number }[]; routes: { route: string; count: number }[]; error_types: { error_type: string; count: number }[];
}
interface Row { id: string; user: string; series: string; message_count: number; last_route: string | null; error_code: string | null; failed_requests: number; last_message_at: string }
interface Detail { id: string; user: string; series: string; messages: Message[]; requests: { id: string; status: string; attempt: number; error_type: string | null; duration_ms: number | null }[] }

const ERROR_LABELS: Record<string, string> = { timeout: "시간 초과", openai: "AI 서비스 연결", internal: "내부 오류", interrupted: "서버 재시작" };
const SERIES: Record<string, string> = { w10n: "W10**N", w1310n: "W1310**N" };
const days = ref(7);
const stats = ref<Stats | null>(null);
const rows = ref<Row[]>([]);
const total = ref(0);
const page = ref(1);
const detail = ref<Detail | null>(null);
const asTable = ref(false);
const hover = ref<number | null>(null);

const sec = (ms: number | null) => (ms == null ? "-" : `${(ms / 1000).toFixed(1)}초`);
// 증감: 늘면 좋은 지표(상담·답변)와 늘면 나쁜 지표(오류·응답시간)를 구분해 색과 아이콘을 붙입니다.
function delta(cur: number | null, prev: number | null, higherIsBad: boolean, unit = "") {
  if (cur == null || prev == null || cur === prev) return null;
  const diff = cur - prev;
  const bad = higherIsBad ? diff > 0 : diff < 0;
  const text = unit === "s" ? `${Math.abs(diff / 1000).toFixed(1)}초` : `${Math.abs(diff)}`;
  return { text: `${diff > 0 ? "+" : "−"}${text}`, bad };
}
const tiles = computed(() => {
  if (!stats.value) return [];
  const c = stats.value.current, p = stats.value.previous;
  return [
    { label: "상담 시작", value: `${c.conversations}`, d: delta(c.conversations, p.conversations, false) },
    { label: "완료된 답변", value: `${c.answers}`, d: delta(c.answers, p.answers, false) },
    { label: "답변 실패", value: `${c.errors}`, d: delta(c.errors, p.errors, true) },
    { label: "응답시간 중앙값", value: sec(c.median_ms), d: delta(c.median_ms, p.median_ms, true, "s") },
    { label: "응답시간 P95", value: sec(c.p95_ms), d: delta(c.p95_ms, p.p95_ms, true, "s") },
  ];
});
const maxDaily = computed(() => Math.max(1, ...(stats.value?.daily_answers.map((d) => d.count) || [1])));
const ticks = computed(() => { const m = maxDaily.value, step = Math.max(1, Math.ceil(m / 4)); return [0, step, step * 2, step * 3, step * 4].filter((t) => t <= Math.max(m, step * 4)); });
const top = computed(() => ticks.value[ticks.value.length - 1] || 1);
const maxIdx = computed(() => { const d = stats.value?.daily_answers || []; return d.reduce((b, x, i) => (x.count > d[b].count ? i : b), 0); });
const routeTotal = computed(() => stats.value?.routes.reduce((s, r) => s + r.count, 0) || 0);
const errorMax = computed(() => Math.max(1, ...(stats.value?.error_types.map((e) => e.count) || [1])));
function dayLabel(iso: string) { const [, m, d] = iso.split("-"); return `${Number(m)}/${Number(d)}`; }
function when(iso: string) { return new Date(iso).toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }); }

async function loadStats() { stats.value = await get<Stats>(`/api/admin/stats?days=${days.value}`); }
async function loadRows() { const r = await get<{ items: Row[]; total: number }>(`/api/admin/conversations?page=${page.value}&size=20`); rows.value = r.items; total.value = r.total; }
async function open(id: string) { detail.value = await get<Detail>(`/api/admin/conversations/${id}`); }
watch(days, loadStats);
watch(page, loadRows);
onMounted(() => { loadStats(); loadRows(); });
</script>

<template>
  <main class="page">
    <div class="page-head">
      <h1>관리자</h1>
      <span v-if="stats" class="desc">{{ stats.from }} ~ {{ stats.to }} (한국 시간)</span>
      <div class="right">
        <div class="seg" role="group" aria-label="기간">
          <button v-for="d in [7, 30, 90]" :key="d" :class="{ on: days === d }" @click="days = d">{{ d }}일</button>
        </div>
      </div>
    </div>

    <template v-if="stats">
      <p v-if="!stats.has_data" class="empty-box" style="margin-bottom: 16px">이 기간에는 데이터가 없어요.</p>
      <div class="tiles">
        <div v-for="t in tiles" :key="t.label" class="card tile">
          <span class="t-label">{{ t.label }}</span>
          <span class="t-value tnum">{{ t.value }}</span>
          <span v-if="t.d" class="t-delta" :class="t.d.bad ? 'bad' : 'good'">
            <Icon :name="t.d.bad ? 'alert' : 'check'" :size="13" />이전 {{ days }}일 대비 {{ t.d.text }}
          </span>
          <span v-else class="t-delta muted">이전 기간과 같음</span>
        </div>
      </div>

      <div class="charts">
        <section class="card chart wide">
          <header><h3>일별 완료 답변</h3>
            <button class="btn sm ghost" @click="asTable = !asTable"><Icon name="table" :size="14" />{{ asTable ? "차트로 보기" : "표로 보기" }}</button>
          </header>
          <table v-if="asTable" class="data">
            <thead><tr><th>날짜</th><th>완료 답변</th></tr></thead>
            <tbody><tr v-for="d in stats.daily_answers" :key="d.date"><td>{{ d.date }}</td><td class="tnum">{{ d.count }}</td></tr></tbody>
          </table>
          <div v-else class="colchart" role="img" :aria-label="`일별 완료 답변, 최대 ${maxDaily}건`">
            <div class="grid"><div v-for="t in [...ticks].reverse()" :key="t" class="gl"><span class="tnum">{{ t }}</span></div></div>
            <div class="cols">
              <div v-for="(d, i) in stats.daily_answers" :key="d.date" class="col" @mouseenter="hover = i" @mouseleave="hover = null" @focus="hover = i" @blur="hover = null" tabindex="0">
                <div class="bar-area">
                  <span v-if="i === maxIdx && d.count && hover === null" class="val tnum" :style="{ bottom: `calc(${(d.count / top) * 100}% + 4px)` }">{{ d.count }}</span>
                  <i class="bar" :style="{ height: `${(d.count / top) * 100}%` }" />
                  <span v-if="hover === i" class="tip" role="tooltip"><b>{{ d.date }}</b>완료 답변 {{ d.count }}건</span>
                </div>
                <span v-if="stats.days <= 14 || i % Math.ceil(stats.days / 10) === 0" class="x">{{ dayLabel(d.date) }}</span>
              </div>
            </div>
          </div>
        </section>
        <section class="card chart">
          <header><h3>판단 분포</h3><span class="muted tnum">{{ routeTotal }}건</span></header>
          <ul class="hbars">
            <li v-for="r in stats.routes" :key="r.route">
              <span class="hl"><RouteBadge :route="r.route" /></span>
              <span class="track"><i :style="{ width: routeTotal ? `${(r.count / routeTotal) * 100}%` : '0' }" /></span>
              <span class="hv tnum">{{ r.count }}<small v-if="routeTotal"> {{ Math.round((r.count / routeTotal) * 100) }}%</small></span>
            </li>
          </ul>
        </section>
        <section class="card chart">
          <header><h3>답변 실패 유형</h3></header>
          <ul v-if="stats.error_types.length" class="hbars">
            <li v-for="e in stats.error_types" :key="e.error_type">
              <span class="hl">{{ ERROR_LABELS[e.error_type] || e.error_type }}</span>
              <span class="track"><i :style="{ width: `${(e.count / errorMax) * 100}%` }" /></span>
              <span class="hv tnum">{{ e.count }}</span>
            </li>
          </ul>
          <p v-else class="empty-box">실패한 답변이 없어요.</p>
        </section>
      </div>
    </template>

    <div class="lower">
      <section class="card list">
        <header><h3>상담 목록</h3><span class="muted">이메일은 가려서 보여요</span></header>
        <div class="table-wrap">
          <table class="data">
            <thead><tr><th>마지막 대화</th><th>사용자</th><th>시리즈</th><th>메시지</th><th>마지막 판단</th><th>실패</th></tr></thead>
            <tbody>
              <tr v-for="r in rows" :key="r.id" :class="{ on: detail?.id === r.id }" tabindex="0" @click="open(r.id)" @keydown.enter="open(r.id)">
                <td class="tnum">{{ when(r.last_message_at) }}</td><td>{{ r.user }}</td><td>{{ SERIES[r.series] || r.series }}</td>
                <td class="tnum">{{ r.message_count }}</td>
                <td><RouteBadge v-if="r.last_route" :route="r.last_route" /><span v-else class="muted">-</span> <span v-if="r.error_code" class="code">{{ r.error_code }}</span></td>
                <td class="tnum" :class="{ bad: r.failed_requests }">{{ r.failed_requests || "-" }}</td>
              </tr>
              <tr v-if="!rows.length"><td colspan="6" class="muted" style="text-align: center; padding: 20px">상담이 없어요.</td></tr>
            </tbody>
          </table>
        </div>
        <nav v-if="total > 20" class="pg">
          <button class="btn sm" :disabled="page === 1" @click="page--">이전</button><span class="muted tnum">{{ page }} / {{ Math.ceil(total / 20) }}</span>
          <button class="btn sm" :disabled="page * 20 >= total" @click="page++">다음</button>
        </nav>
      </section>
      <section class="card detail">
        <template v-if="detail">
          <header><h3>상담 원문</h3><span class="muted">{{ detail.user }} · {{ SERIES[detail.series] || detail.series }}</span></header>
          <p class="notice"><Icon name="shield" :size="14" />원문 열람은 감사 기록에 남아요.</p>
          <ol class="msgs">
            <li v-for="m in detail.messages" :key="m.id" :class="m.role">
              <span class="who">{{ m.role === "user" ? (m.kind === "checklist_report" ? "고객(점검 결과)" : "고객") : "AI" }}</span>
              <RouteBadge v-if="m.result" :route="m.result.route" />
              <p>{{ m.content }}</p>
              <small v-if="m.result" class="muted">근거 {{ m.result.evidence_pages.join(", ") || "없음" }} · {{ sec(m.result.duration_ms) }}{{ m.result.revision_failed ? " · 검사 일부 미통과" : "" }}</small>
            </li>
          </ol>
          <h4>처리 기록</h4>
          <ul class="reqs"><li v-for="r in detail.requests" :key="r.id" class="tnum">{{ r.attempt }}차 · {{ r.status }}{{ r.error_type ? ` (${ERROR_LABELS[r.error_type] || r.error_type})` : "" }} · {{ sec(r.duration_ms) }}</li></ul>
        </template>
        <div v-else class="empty-box">왼쪽 목록에서 상담을 고르면 원문과 처리 기록을 볼 수 있어요.</div>
      </section>
    </div>
  </main>
</template>

<style scoped>
.tiles { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; margin-bottom: 16px; }
.tile { padding: 14px 16px; display: flex; flex-direction: column; gap: 4px; }
.t-label { font-size: 12.5px; color: var(--ink-2); font-weight: 600; }
.t-value { font-size: 26px; font-weight: 750; letter-spacing: -0.02em; color: var(--ink); }
.t-delta { font-size: 12px; display: inline-flex; align-items: center; gap: 4px; }
.t-delta.good { color: var(--good); }
.t-delta.bad { color: var(--bad); }
.charts { display: grid; grid-template-columns: minmax(0, 1.6fr) minmax(0, 1fr) minmax(0, 1fr); gap: 12px; margin-bottom: 16px; }
.chart { padding: 14px 16px; min-width: 0; }
.chart header, .list header, .detail header { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 10px; }
h3 { font-size: 13.5px; font-weight: 700; }
.colchart { position: relative; height: 200px; margin-top: 24px; padding-left: 28px; }
.grid { position: absolute; inset: 0 0 22px 28px; display: flex; flex-direction: column; justify-content: space-between; }
.gl { border-top: 1px solid var(--line-2); position: relative; height: 0; }
.gl span { position: absolute; left: -28px; top: -8px; width: 22px; text-align: right; font-size: 11px; color: var(--ink-3); }
.cols { position: absolute; inset: 0 0 0 28px; display: flex; gap: 2px; }
.col { flex: 1; display: flex; flex-direction: column; align-items: center; min-width: 0; outline: 0; }
.bar-area { flex: 1; width: 100%; display: flex; align-items: flex-end; justify-content: center; position: relative; padding-bottom: 0; margin-bottom: 22px; }
.bar { display: block; width: min(24px, 70%); background: #0d9488; border-radius: 4px 4px 0 0; min-height: 0; }
.col:hover .bar, .col:focus .bar { background: var(--teal-800); }
.val { position: absolute; font-size: 11.5px; font-weight: 650; color: var(--ink); }
.tip { position: absolute; bottom: calc(100% + 8px); left: 50%; transform: translateX(-50%); background: var(--ink); color: #fff; font-size: 11.5px; padding: 6px 8px; border-radius: 6px; white-space: nowrap; display: flex; flex-direction: column; z-index: 2; pointer-events: none; }
.x { position: absolute; bottom: 0; font-size: 11px; color: var(--ink-3); }
.col { position: relative; }
.hbars { list-style: none; display: flex; flex-direction: column; gap: 10px; }
.hbars li { display: grid; grid-template-columns: minmax(0, 132px) minmax(0, 1fr) 64px; align-items: center; gap: 8px; font-size: 12.5px; color: var(--ink-2); }
.track { height: 12px; background: transparent; border-radius: 0 4px 4px 0; }
.track i { display: block; height: 100%; background: #0d9488; border-radius: 0 4px 4px 0; }
.hv { text-align: right; color: var(--ink); font-weight: 650; }
.hv small { color: var(--ink-3); font-weight: 500; }
table.data { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.data th { text-align: left; font-size: 12px; color: var(--ink-3); font-weight: 600; padding: 8px 10px; border-bottom: 1px solid var(--line); white-space: nowrap; }
.data td { padding: 9px 10px; border-bottom: 1px solid var(--line-2); white-space: nowrap; }
.data tbody tr { cursor: pointer; }
.data tbody tr:hover, .data tbody tr.on { background: #f8fafc; }
td.bad { color: var(--bad); font-weight: 650; }
.lower { display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr); gap: 12px; align-items: start; }
.list, .detail { padding: 14px 16px; min-width: 0; }
.table-wrap { overflow-x: auto; }
.pg { display: flex; justify-content: center; align-items: center; gap: 10px; margin-top: 10px; font-size: 12.5px; }
.msgs { list-style: none; display: flex; flex-direction: column; gap: 10px; margin: 12px 0; max-height: 460px; overflow-y: auto; }
.msgs li { padding: 10px; border-radius: 8px; background: var(--bg); font-size: 12.5px; display: flex; flex-direction: column; gap: 4px; }
.msgs li.assistant { background: #fff; border: 1px solid var(--line); }
.msgs .who { font-size: 11.5px; font-weight: 700; color: var(--ink-3); }
.msgs p { white-space: pre-wrap; }
h4 { font-size: 12.5px; font-weight: 700; margin-bottom: 6px; }
.reqs { list-style: none; font-size: 12px; color: var(--ink-2); display: flex; flex-direction: column; gap: 2px; }
@media (max-width: 1199px) { .tiles { grid-template-columns: repeat(3, minmax(0, 1fr)); } .charts, .lower { grid-template-columns: minmax(0, 1fr); } }
@media (max-width: 767px) { .tiles { grid-template-columns: repeat(2, minmax(0, 1fr)); } .hbars li { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) 56px; } }
</style>
