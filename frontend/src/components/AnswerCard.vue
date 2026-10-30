<script setup lang="ts">
import MarkdownIt from "markdown-it";
import { computed, reactive, ref } from "vue";
import { CHECK_OUTCOMES, CHECK_STATUSES, type ChecklistItem, type Message } from "../api";
import Icon from "./Icon.vue";
import RouteBadge from "./RouteBadge.vue";

const props = defineProps<{ message: Message; items: ChecklistItem[]; latest: boolean; locked: boolean; activePage: number | null }>();
const emit = defineEmits<{
  cite: [page: number]; bookmark: []; saveMemory: [];
  report: [results: { item_id: string; status: string; outcome: string }[], note: string];
}>();

// html:false — 답변 안의 HTML은 글자로 보여 줍니다. [PDF n쪽]만 인용 버튼으로 바꿉니다.
const md = new MarkdownIt({ html: false, linkify: false, breaks: true });
const body = computed(() => {
  // 답변 원문은 '판단: …\n이유: …\n\n안내' 형식입니다. 판단·이유는 머리에 따로 보여 주므로 본문에서 뺍니다.
  const text = props.message.content.replace(/^판단:[^\n]*\n이유:[^\n]*\n*/, "");
  return md.render(text).replace(/\[PDF\s*(\d+)쪽\]/g, (_m, p) => `<button type="button" class="cite" data-page="${p}">PDF ${p}쪽</button>`);
});
function onBodyClick(e: MouseEvent) {
  const page = (e.target as HTMLElement).closest<HTMLElement>("[data-page]")?.dataset.page;
  if (page) emit("cite", Number(page));
}

const r = computed(() => props.message.result!);
const time = computed(() => new Date(props.message.created_at).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" }));
const applied = computed(() => props.message.applied_memories || []);
const selfItems = computed(() => props.items.filter((i) => i.kind === "self_check"));
const doneCount = computed(() => selfItems.value.filter((i) => i.status !== "미확인").length);
const nextId = computed(() => selfItems.value.find((i) => i.enabled && i.status === "미확인")?.id);

const STATUS_CLASS: Record<string, string> = { "확인 완료": "done", "수행 어려움": "hard", "해당 없음": "na", "미확인": "todo" };
const OUTCOME_CLASS: Record<string, string> = { "해결됨": "good", "이상 없음": "good", "해결되지 않음": "bad", "이상 발견": "bad" };

const editing = ref(false);
const note = ref("");
const draft = reactive<Record<string, { status: string; outcome: string }>>({});
function openReport() {
  for (const i of props.items) draft[i.id] = { status: i.status, outcome: i.outcome };
  note.value = "";
  editing.value = true;
}
const changed = computed(() => props.items.filter((i) => i.enabled && draft[i.id] && (draft[i.id].status !== i.status || draft[i.id].outcome !== i.outcome)));
function submitReport() {
  emit("report", changed.value.map((i) => ({ item_id: i.id, ...draft[i.id] })), note.value);
  editing.value = false;
}
</script>

<template>
  <article class="card answer" :id="`m-${message.id}`">
    <div class="ans-head">
      <RouteBadge :route="r.route" />
      <span class="meta"><Icon name="clock" :size="14" />{{ time }}</span>
      <div class="ans-actions">
        <button class="icon-btn" :class="{ on: message.bookmarked }" :title="message.bookmarked ? '북마크 해제' : '북마크'" @click="emit('bookmark')">
          <Icon :name="message.bookmarked ? 'star-fill' : 'star'" />
        </button>
        <button v-if="latest && r.retrieved_pages.length" class="btn sm ghost" :disabled="locked" @click="emit('saveMemory')"><Icon name="note" :size="14" />기억으로 저장</button>
      </div>
    </div>
    <p class="ans-reason"><b>판단 이유</b>{{ r.reason }}</p>
    <div class="ans-body" @click="onBodyClick" v-html="body" />

    <p v-if="applied.length" class="mem-applied">
      <Icon name="note" :size="14" />기억 반영:
      <template v-for="(m, i) in applied" :key="i">
        <span v-if="m.deleted" class="muted">삭제된 기억</span>
        <span v-else>{{ m.symptom }} → {{ m.action }} ({{ m.outcome }}, v{{ m.version }})</span><span v-if="i < applied.length - 1">, </span>
      </template>
    </p>

    <section v-if="items.length" class="checklist">
      <div class="cl-head">
        <b>점검 체크리스트</b>
        <span v-if="selfItems.length" class="cl-progress">{{ doneCount }}/{{ selfItems.length }} 확인<span class="bar"><i :style="{ width: `${(doneCount / selfItems.length) * 100}%` }" /></span></span>
      </div>
      <ul class="cl-items">
        <li v-for="item in items" :key="item.id" class="cl-item"
            :class="[STATUS_CLASS[item.status], { next: item.id === nextId && latest, off: !item.enabled }]">
          <span class="cl-box"><Icon v-if="item.status === '확인 완료'" name="check" :size="13" /><Icon v-else-if="item.status === '해당 없음'" name="x" :size="12" /></span>
          <div class="cl-main">
            <div class="cl-title">
              {{ item.title }}
              <span v-if="item.kind === 'contact_service'" class="chip" style="background: var(--amber-50); color: var(--amber-800)">서비스 문의</span>
              <span v-if="item.id === nextId && latest" class="next-tag">다음 확인</span>
            </div>
            <p v-if="item.detail" class="cl-detail">{{ item.detail }}</p>
            <div v-if="editing && item.enabled" class="cl-edit">
              <div class="seg" role="group" :aria-label="`${item.title} 수행 여부`">
                <button v-for="s in CHECK_STATUSES" :key="s" type="button" :class="{ on: draft[item.id].status === s }" @click="draft[item.id].status = s">{{ s }}</button>
              </div>
              <div class="seg" role="group" :aria-label="`${item.title} 결과`">
                <button v-for="o in CHECK_OUTCOMES" :key="o" type="button" :class="{ on: draft[item.id].outcome === o }" @click="draft[item.id].outcome = o">{{ o }}</button>
              </div>
            </div>
            <p v-if="!item.enabled" class="cl-detail muted">답변 검사를 통과하지 못해 이 항목은 결과를 알릴 수 없어요.</p>
          </div>
          <div v-if="!editing" class="cl-tags right">
            <span class="st" :class="STATUS_CLASS[item.status]">{{ item.status }}</span>
            <span v-if="item.outcome !== '결과 불명'" class="oc" :class="OUTCOME_CLASS[item.outcome] || 'unk'">{{ item.outcome }}</span>
            <button v-for="p in item.pages" :key="p" class="cite" :class="{ on: p === activePage }" @click="emit('cite', p)">PDF {{ p }}쪽</button>
          </div>
        </li>
      </ul>
      <div v-if="latest" class="cl-foot">
        <template v-if="!editing">
          <button class="btn sm soft" :disabled="locked || !items.some((i) => i.enabled)" @click="openReport">점검 결과 알려주기</button>
          <span>결과를 알려주시면 다음 단계를 안내해 드려요.</span>
        </template>
        <template v-else>
          <input v-model="note" class="field note" maxlength="500" placeholder="덧붙일 말(선택)" />
          <button class="btn sm ghost" @click="editing = false">취소</button>
          <button class="btn sm primary" :disabled="locked || !changed.length" @click="submitReport">보내기</button>
        </template>
      </div>
    </section>

    <div class="ans-foot">
      <span v-if="r.evidence_pages.length"><Icon name="file" :size="14" />근거 {{ r.evidence_pages.map((p) => `PDF ${p}쪽`).join(", ") }}</span>
      <span v-if="r.revision_failed" style="color: var(--amber-700)"><Icon name="alert" :size="14" />답변 검사 일부 미통과</span>
      <span v-if="r.duration_ms">{{ (r.duration_ms / 1000).toFixed(1) }}초</span>
    </div>
  </article>
</template>

<style scoped>
.mem-applied { margin-top: 10px; font-size: 12px; color: var(--teal-800); background: var(--teal-50); border: 1px solid var(--teal-200); border-radius: 8px; padding: 6px 10px; display: flex; align-items: center; gap: 4px; flex-wrap: wrap; }
.cl-edit { display: flex; flex-direction: column; gap: 6px; margin-top: 8px; }
.cl-item.off { opacity: .6; }
.cl-tags.right { flex-wrap: wrap; justify-content: flex-end; max-width: 46%; }
.cite.on { background: var(--teal-700); color: #fff; border-color: var(--teal-700); }
.note { flex: 1; min-width: 0; height: 30px; }
.cl-foot { flex-wrap: wrap; }
@media (max-width: 767px) {
  .cl-item { flex-wrap: wrap; }
  .cl-tags.right { max-width: none; width: 100%; justify-content: flex-start; padding-left: 30px; }
}
</style>
