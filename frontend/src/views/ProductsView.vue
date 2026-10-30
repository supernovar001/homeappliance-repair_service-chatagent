<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { ApiError, del, get, patch, post, type ConversationSummary, type Memory, type Product, type SupportedModel } from "../api";
import Icon from "../components/Icon.vue";
import WashTower from "../components/WashTower.vue";
import { useSession } from "../stores/session";

const session = useSession();
const models = ref<SupportedModel[]>([]);
const selectedId = ref("");
const tab = ref<"memories" | "history">("memories");
const memories = ref<Memory[]>([]);
const history = ref<ConversationSummary[]>([]);
const error = ref("");
const form = ref({ supported_model_id: "", nickname: "", model_code: "" });
const editing = ref<Memory | null>(null);

const selected = computed(() => session.products.find((p) => p.id === selectedId.value) || null);
const confirmedCount = computed(() => memories.value.filter((m) => m.status === "confirmed").length);
const draftCount = computed(() => memories.value.filter((m) => m.status === "draft").length);
const OUTCOMES = ["해결됨", "해결되지 않음", "결과 미확인"];
const OC_CLASS: Record<string, string> = { "해결됨": "good", "해결되지 않음": "bad", "결과 미확인": "unk" };

function fail(e: unknown) { error.value = e instanceof ApiError ? e.message : "요청을 처리하지 못했어요."; }
function day(iso: string | null) { return iso ? new Date(iso).toLocaleDateString("ko-KR", { month: "long", day: "numeric" }) : ""; }

async function loadSelected() {
  if (!selectedId.value) return;
  const [ms, hs] = await Promise.all([
    get<Memory[]>(`/api/products/${selectedId.value}/memories`),
    get<{ items: ConversationSummary[] }>(`/api/conversations?limit=100&product_id=${selectedId.value}`),
  ]);
  memories.value = ms;
  history.value = hs.items;
}

async function register() {
  error.value = "";
  try {
    const p = await post<Product>("/api/products", { ...form.value, model_code: form.value.model_code || null });
    await session.loadProducts();
    selectedId.value = p.id;
    form.value = { supported_model_id: models.value[0]?.id || "", nickname: "", model_code: "" };
  } catch (e) { fail(e); }
}

async function rename(p: Product) {
  const nickname = window.prompt("제품 별명", p.nickname);
  if (!nickname?.trim()) return;
  try { await patch(`/api/products/${p.id}`, { nickname }); await session.loadProducts(); } catch (e) { fail(e); }
}

async function saveMemory() {
  const m = editing.value;
  if (!m) return;
  try {
    await patch(`/api/memories/${m.id}`, { symptom: m.symptom, action: m.action, outcome: m.outcome, confirm: m.status === "draft" });
    editing.value = null;
    await Promise.all([loadSelected(), session.loadProducts()]);
  } catch (e) { fail(e); }
}

async function removeMemory(m: Memory) {
  const msg = m.status === "draft" ? "이 초안을 지울까요?" : "이 기억을 지울까요? 지난 답변에서도 '삭제된 기억'으로 바뀌어요.";
  if (!window.confirm(msg)) return;
  try { await del(`/api/memories/${m.id}`); await Promise.all([loadSelected(), session.loadProducts()]); } catch (e) { fail(e); }
}

watch(selectedId, loadSelected);
onMounted(async () => {
  models.value = await get<SupportedModel[]>("/api/supported-models");
  form.value.supported_model_id = models.value[0]?.id || "";
  await session.loadProducts();
  selectedId.value = session.products[0]?.id || "";
});
</script>

<template>
  <main class="page">
    <div class="page-head">
      <h1>내 제품</h1>
      <span class="desc">사용설명서(MFL71831423)가 다루는 워시타워만 등록할 수 있어요.</span>
    </div>
    <p v-if="error" class="error-box" style="margin-bottom: 12px"><Icon name="alert" />{{ error }}</p>
    <div class="layout">
      <div class="main-col">
        <div class="prod-grid">
          <div v-for="p in session.products" :key="p.id" class="card pcard" :class="{ on: p.id === selectedId }" @click="selectedId = p.id">
            <span class="pic"><WashTower :width="52" /></span>
            <div class="info">
              <div class="name">{{ p.nickname }} <button class="icon-btn" title="별명 바꾸기" @click.stop="rename(p)"><Icon name="pencil" :size="14" /></button></div>
              <span class="spec">{{ p.supported_model.series }} 시리즈 · 세탁기 {{ p.supported_model.washer_model }} + 건조기 {{ p.supported_model.dryer_model }}</span>
              <span class="model">{{ p.model_code || "모델명 입력 안 함" }} · {{ day(p.created_at) }} 등록</span>
              <div class="stats"><span>상담 <b>{{ p.conversation_count }}</b>건</span><span>확인된 기억 <b>{{ p.memory_count }}</b>개</span><span v-if="p.draft_memory_count">확인 대기 <b>{{ p.draft_memory_count }}</b>개</span></div>
              <div class="acts"><RouterLink :to="{ path: '/consult', query: { product: p.id } }" class="btn sm" :class="{ primary: p.id === selectedId }" @click.stop><Icon name="plus" :size="14" />이 제품으로 새 상담</RouterLink></div>
            </div>
          </div>
          <div v-if="!session.products.length" class="empty-box">아직 등록한 제품이 없어요. 오른쪽에서 등록해 주세요.</div>
        </div>

        <section v-if="selected" class="card">
          <div class="tabs" role="tablist">
            <button role="tab" :class="{ on: tab === 'memories' }" @click="tab = 'memories'">기억 <span class="cnt">확인 {{ confirmedCount }} · 대기 {{ draftCount }}</span></button>
            <button role="tab" :class="{ on: tab === 'history' }" @click="tab = 'history'">상담 이력 <span class="cnt">{{ history.length }}</span></button>
          </div>
          <div v-if="tab === 'memories'" class="table-wrap">
            <table>
              <thead><tr><th>확인일</th><th>증상</th><th>수행한 조치</th><th>결과</th><th>버전</th><th>출처 상담</th><th /></tr></thead>
              <tbody>
                <tr v-for="m in memories" :key="m.id" :class="{ draft: m.status === 'draft' }">
                  <td><span v-if="m.status === 'draft'" class="draft-badge">확인 대기</span><template v-else>{{ day(m.confirmed_at) }}</template></td>
                  <td>{{ m.symptom }}</td>
                  <td>{{ m.action }}</td>
                  <td><span class="oc" :class="OC_CLASS[m.outcome]">{{ m.outcome }}</span></td>
                  <td><span class="ver">{{ m.status === "draft" ? "초안" : `v${m.version}` }}</span><span v-if="m.version > 1" class="sub">{{ day(m.updated_at) }} 수정</span></td>
                  <td>
                    <RouterLink v-if="m.source_conversation_id" :to="`/consult/${m.source_conversation_id}`" class="link">상담 보기<Icon name="chev-right" :size="14" /></RouterLink>
                    <span v-else class="gone">보관 기간이 지나 삭제됨</span>
                  </td>
                  <td><div class="row-acts">
                    <button v-if="m.status === 'draft'" class="btn sm soft" @click="editing = { ...m }">확인하기</button>
                    <button v-else class="icon-btn" title="고치기" @click="editing = { ...m }"><Icon name="pencil" :size="14" /></button>
                    <button class="icon-btn" title="지우기" @click="removeMemory(m)"><Icon name="x" :size="14" /></button>
                  </div></td>
                </tr>
                <tr v-if="!memories.length"><td colspan="7" class="muted" style="text-align: center; padding: 20px">상담 답변에서 '기억으로 저장'을 누르면 여기에 쌓여요.</td></tr>
              </tbody>
            </table>
            <p class="table-note"><Icon name="info" :size="14" /><span>확인된 기억은 이 제품의 새 상담에 기본으로 적용돼요. 고친 내용은 다음 상담부터 쓰이고 지난 답변은 그대로예요.<br>지운 기억은 지난 답변에서도 ‘삭제된 기억’으로 바뀌어요. 상담 원문이 90일 보관 기간으로 지워져도 확인된 기억은 남아요.</span></p>
          </div>
          <ul v-else class="hist-list">
            <li v-for="h in history" :key="h.id"><RouterLink :to="`/consult/${h.id}`" class="hist"><b>{{ h.title }}</b><span>{{ day(h.last_message_at) }}</span></RouterLink></li>
            <li v-if="!history.length" class="muted" style="padding: 16px">아직 상담이 없어요.</li>
          </ul>
        </section>
      </div>

      <aside class="card form">
        <h3>제품 등록</h3>
        <div>
          <span class="l">모델 시리즈</span>
          <div class="series" role="radiogroup">
            <button v-for="m in models" :key="m.id" type="button" role="radio" :aria-checked="form.supported_model_id === m.id" class="opt"
                    :class="{ on: form.supported_model_id === m.id }" @click="form.supported_model_id = m.id">
              <span class="rd" /><div><b>{{ m.series }}</b><span>세탁기 {{ m.washer_model }} + 건조기 {{ m.dryer_model }}</span></div>
            </button>
          </div>
          <p class="hint">사용설명서 표지에 적힌 모델이에요. * 자리는 색상 등 세부 코드예요.</p>
        </div>
        <label><span class="l">별명</span><input v-model="form.nickname" class="field" maxlength="40" placeholder="예: 우리집 워시타워" /></label>
        <label>
          <span class="l">모델명 <span class="muted" style="font-weight: 500">(선택)</span></span>
          <input v-model="form.model_code" class="field" maxlength="40" placeholder="제품 라벨의 모델명" />
          <p class="hint">입력하면 고른 시리즈의 형식과 맞는지 확인해요.</p>
        </label>
        <button class="btn primary block" :disabled="!form.nickname.trim() || !form.supported_model_id" @click="register">등록하기</button>
        <p class="form-note"><Icon name="info" :size="14" /><span>같은 모델을 여러 대 등록할 수 있어요.<br>제품 삭제는 아직 지원하지 않아요.</span></p>
      </aside>
    </div>

    <template v-if="editing">
      <div class="scrim" @click="editing = null" />
      <div class="dialog" role="dialog" aria-modal="true" aria-labelledby="edit-title">
        <h2 id="edit-title">{{ editing.status === "draft" ? "기억 확인하기" : "기억 고치기" }}</h2>
        <p class="desc">{{ editing.status === "draft" ? "확인하면 이 제품의 다음 상담부터 쓰여요." : "고친 내용은 다음 상담부터 쓰이고, 버전이 올라가요." }}</p>
        <div class="edit-form">
          <label>증상<input v-model="editing.symptom" class="field" maxlength="200" /></label>
          <label>수행한 조치<input v-model="editing.action" class="field" maxlength="300" /></label>
          <div>결과 <div class="seg"><button v-for="o in OUTCOMES" :key="o" type="button" :class="{ on: editing.outcome === o }" @click="editing.outcome = o">{{ o }}</button></div></div>
          <p v-if="editing.evidence" class="muted" style="font-weight: 500">근거 발화: “{{ editing.evidence }}”</p>
        </div>
        <div class="acts"><button class="btn" @click="editing = null">취소</button><button class="btn primary" @click="saveMemory">{{ editing.status === "draft" ? "확인하고 저장" : "저장" }}</button></div>
      </div>
    </template>
  </main>
</template>

<style scoped>
.layout { display: grid; grid-template-columns: minmax(0, 1fr) 340px; gap: 20px; align-items: start; }
.prod-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 14px; margin-bottom: 18px; }
.pcard { padding: 16px; display: flex; gap: 16px; cursor: pointer; }
.pcard.on { border-color: var(--teal-600); box-shadow: 0 0 0 3px var(--teal-50); }
.pcard .pic { width: 84px; height: 112px; border-radius: 12px; background: var(--teal-50); display: grid; place-items: center; color: var(--teal-700); flex: none; }
.pcard .info { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.pcard .name { display: flex; align-items: center; gap: 4px; font-size: 15.5px; font-weight: 700; }
.pcard .spec { font-size: 12.5px; color: var(--ink-2); }
.pcard .model { font-size: 12px; color: var(--ink-3); }
.pcard .stats { display: flex; gap: 12px; font-size: 12px; color: var(--ink-2); margin-top: 4px; flex-wrap: wrap; }
.pcard .stats b { color: var(--ink); }
.pcard .acts { display: flex; gap: 6px; margin-top: 10px; }
.tabs { display: flex; gap: 2px; border-bottom: 1px solid var(--line); padding: 0 16px; }
.tabs button { padding: 12px 10px; font-size: 13px; font-weight: 600; color: var(--ink-3); border: 0; background: none; border-bottom: 2px solid transparent; margin-bottom: -1px; display: inline-flex; gap: 6px; align-items: center; }
.tabs button.on { color: var(--teal-800); border-bottom-color: var(--teal-700); }
.tabs .cnt { font-size: 11px; background: #f1f5f9; color: var(--ink-2); border-radius: 999px; padding: 0 6px; line-height: 17px; }
.tabs .on .cnt { background: var(--teal-100); color: var(--teal-800); }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 13px; min-width: 640px; }
th { text-align: left; font-size: 12px; color: var(--ink-3); font-weight: 600; padding: 10px 12px; border-bottom: 1px solid var(--line); background: #fbfcfd; white-space: nowrap; }
td { padding: 11px 12px; border-bottom: 1px solid var(--line-2); vertical-align: middle; }
tr.draft td { background: #fffdf7; }
td .sub { display: block; font-size: 11.5px; color: var(--ink-3); }
.ver { font-size: 12px; color: var(--ink-2); }
.link { color: var(--teal-700); font-weight: 600; font-size: 12.5px; display: inline-flex; align-items: center; gap: 2px; white-space: nowrap; }
.gone { color: var(--ink-3); font-size: 12px; }
.row-acts { display: flex; gap: 2px; justify-content: flex-end; }
.draft-badge { font-size: 11px; font-weight: 700; color: var(--amber-800); background: var(--amber-50); border: 1px solid var(--amber-200); border-radius: 5px; padding: 0 6px; line-height: 18px; white-space: nowrap; }
.table-note { display: flex; gap: 8px; align-items: flex-start; padding: 12px 16px; font-size: 12.5px; color: var(--ink-2); }
.hist-list { list-style: none; padding: 8px; }
.form { padding: 18px; display: flex; flex-direction: column; gap: 14px; }
.form h3 { font-size: 15px; font-weight: 750; }
.form .l, .form label > .l { font-size: 12.5px; font-weight: 650; color: var(--ink-2); display: block; margin-bottom: 6px; }
.form .field { width: 100%; }
.series { display: flex; flex-direction: column; gap: 8px; }
.series .opt { display: flex; gap: 10px; padding: 10px 12px; border: 1px solid var(--line); border-radius: 10px; align-items: flex-start; background: #fff; text-align: left; }
.series .opt.on { border-color: var(--teal-600); background: var(--teal-50); }
.series .rd { width: 16px; height: 16px; border-radius: 50%; border: 1.5px solid #cbd5e1; flex: none; margin-top: 2px; background: #fff; }
.series .opt.on .rd { border: 5px solid var(--teal-700); }
.series b { font-size: 13.5px; display: block; }
.series span { font-size: 12px; color: var(--ink-2); }
.hint { font-size: 11.5px; color: var(--ink-3); margin-top: 5px; }
.form-note { font-size: 12px; color: var(--ink-3); background: var(--bg); border-radius: 8px; padding: 10px 12px; display: flex; gap: 6px; }
.edit-form { display: flex; flex-direction: column; gap: 10px; font-size: 12.5px; font-weight: 600; color: var(--ink-2); }
.edit-form label, .edit-form > div { display: flex; flex-direction: column; gap: 4px; }
@media (max-width: 1199px) { .layout { grid-template-columns: minmax(0, 1fr); } }
@media (max-width: 767px) { .prod-grid { grid-template-columns: minmax(0, 1fr); } .pcard .pic { width: 64px; height: 88px; } }
</style>
