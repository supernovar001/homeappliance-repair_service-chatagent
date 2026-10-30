<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  ApiError, del, get, newRequestId, patch, post, put,
  type Conversation, type ConversationSummary, type Memory, type Message, type RequestState,
} from "../api";
import AnswerCard from "../components/AnswerCard.vue";
import EvidencePanel from "../components/EvidencePanel.vue";
import Icon from "../components/Icon.vue";
import MemoryDraftDialog from "../components/MemoryDraftDialog.vue";
import RouteBadge from "../components/RouteBadge.vue";
import WashTower from "../components/WashTower.vue";
import { STAGES, STAGE_LABELS, useRequestStream } from "../composables/useRequestStream";
import { useSession } from "../stores/session";

const session = useSession();
const route = useRoute();
const router = useRouter();
const stream = useRequestStream();

const conversations = ref<ConversationSummary[]>([]);
const search = ref("");
const conv = ref<Conversation | null>(null);
const examples = ref<string[]>([]);
const text = ref("");
const error = ref("");
const toast = ref("");
const busy = ref(false);
const drawer = ref(false);
const sheet = ref(false);
const memoryDialog = ref(false);
const threadEl = ref<HTMLElement | null>(null);

// 새 상담 화면에서 고르는 제품과 기억
const newProductId = ref("");
const newMemories = ref<Memory[]>([]);
const newSelected = ref<string[]>([]);

const id = computed(() => (route.params.id as string) || "");
const request = computed(() => conv.value?.request || null);
const running = computed(() => !!request.value && ["queued", "running"].includes(request.value.status));
const failed = computed(() => !!request.value && ["failed", "interrupted"].includes(request.value.status));
const locked = computed(() => busy.value || running.value);
const answers = computed(() => conv.value?.messages.filter((m) => m.kind === "answer") || []);
const latestAnswer = computed(() => answers.value[answers.value.length - 1] || null);
const product = computed(() => session.products.find((p) => p.id === (conv.value?.product_id || newProductId.value)) || null);

// 근거 패널: 보통은 최신 답변의 근거, 이전 답변의 인용을 누르면 그 답변의 근거를 보여 줍니다.
const evidence = ref<{ messageId: string; page: number } | null>(null);
const evidenceMessage = computed(() => answers.value.find((m) => m.id === evidence.value?.messageId) || latestAnswer.value);

function itemsOf(m: Message) { return conv.value?.checklist.filter((i) => i.message_id === m.id) || []; }
function flash(msg: string) { toast.value = msg; window.setTimeout(() => (toast.value = ""), 2600); }
function fail(e: unknown) { error.value = e instanceof ApiError ? e.message : "요청을 처리하지 못했습니다."; }

async function loadList() {
  const r = await get<{ items: ConversationSummary[] }>(`/api/conversations?limit=50&q=${encodeURIComponent(search.value)}`);
  conversations.value = r.items;
}

async function loadConversation(scroll = true) {
  if (!id.value) { conv.value = null; return; }
  try {
    conv.value = await get<Conversation>(`/api/conversations/${id.value}`);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) { router.replace("/consult"); flash("상담을 찾을 수 없어요."); return; }
    throw e;
  }
  if (running.value) follow(request.value!);
  if (scroll) scrollToEnd();
  const target = route.query.m as string | undefined;
  if (target) nextTick(() => document.getElementById(`m-${target}`)?.scrollIntoView({ block: "center" }));
}

function scrollToEnd() { nextTick(() => threadEl.value?.scrollTo({ top: threadEl.value.scrollHeight })); }

function follow(req: RequestState) {
  stream.watch(req.id, {
    onDone: async () => { await loadConversation(); evidence.value = null; loadList(); },
    onError: async (message) => { error.value = message; await loadConversation(); },
  });
}

async function startNewWith(productId: string) {
  newProductId.value = productId;
  newMemories.value = [];
  newSelected.value = [];
  if (!productId) return;
  const ms = await get<Memory[]>(`/api/products/${productId}/memories`);
  newMemories.value = ms.filter((m) => m.status === "confirmed");
  newSelected.value = newMemories.value.slice(0, 10).map((m) => m.id);
}

async function send() {
  const content = text.value.trim();
  if (!content || locked.value) return;
  error.value = "";
  busy.value = true;
  try {
    let conversationId = id.value;
    if (!conversationId) {
      if (!newProductId.value) { error.value = "상담할 제품을 먼저 골라 주세요."; return; }
      const created = await post<Conversation>("/api/conversations", { product_id: newProductId.value });
      conversationId = created.id;
      if (newSelected.value.length !== created.will_apply.length || newSelected.value.some((m) => !created.will_apply.includes(m))) {
        await put(`/api/conversations/${conversationId}/memory-selection`, { memory_ids: newSelected.value });
      }
    }
    const r = await post<{ request: RequestState; user_message: Message }>(`/api/conversations/${conversationId}/messages`,
      { content, client_request_id: newRequestId() });
    text.value = "";
    if (conversationId !== id.value) {
      await router.replace(`/consult/${conversationId}`);
    } else {
      conv.value!.messages.push(r.user_message);
      conv.value!.request = r.request;
      follow(r.request);
      scrollToEnd();
    }
    loadList();
  } catch (e) { fail(e); } finally { busy.value = false; }
}

async function retry() {
  if (!request.value) return;
  error.value = "";
  try {
    const r = await post<{ request: RequestState }>(`/api/requests/${request.value.id}/retry`);
    conv.value!.request = r.request;
    follow(r.request);
  } catch (e) { fail(e); }
}

async function report(results: { item_id: string; status: string; outcome: string }[], note: string) {
  error.value = "";
  try {
    const r = await post<{ request: RequestState; user_message: Message }>(`/api/conversations/${id.value}/checklist-results`,
      { client_request_id: newRequestId(), results, note });
    await loadConversation();
    follow(r.request);
  } catch (e) { fail(e); }
}

async function toggleBookmark(m: Message) {
  try {
    if (m.bookmarked) await del(`/api/messages/${m.id}/bookmark`); else await put(`/api/messages/${m.id}/bookmark`, {});
    m.bookmarked = !m.bookmarked;
    flash(m.bookmarked ? "북마크에 저장했어요." : "북마크를 해제했어요.");
  } catch (e) { fail(e); }
}

async function toggleMemory(memoryId: string) {
  if (!conv.value || locked.value) return;
  const now = conv.value.memories.filter((m) => m.selected).map((m) => m.id);
  const next = now.includes(memoryId) ? now.filter((x) => x !== memoryId) : [...now, memoryId];
  try {
    conv.value = await put<Conversation>(`/api/conversations/${conv.value.id}/memory-selection`, { memory_ids: next });
  } catch (e) { fail(e); }
}

async function renameConversation() {
  const title = window.prompt("상담 제목", conv.value?.title);
  if (!title?.trim() || !conv.value) return;
  try { conv.value = await patch<Conversation>(`/api/conversations/${conv.value.id}`, { title }); loadList(); } catch (e) { fail(e); }
}

async function removeConversation() {
  if (!conv.value) return;
  const n = conv.value.source_memory_count;
  const msg = n ? `이 상담과 여기서 저장한 기억 ${n}개를 지울까요? 지운 기억은 다른 상담의 답변에서도 '삭제된 기억'으로 바뀌어요.` : "이 상담을 지울까요?";
  if (!window.confirm(msg)) return;
  try { await del(`/api/conversations/${conv.value.id}`); await router.replace("/consult"); loadList(); flash("상담을 지웠어요."); } catch (e) { fail(e); }
}

function cite(m: Message, page: number) {
  evidence.value = { messageId: m.id, page };
  sheet.value = true;
}

function onKey(e: KeyboardEvent) {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); }
}

function groupLabel(iso: string) {
  const d = new Date(iso), today = new Date();
  if (d.toDateString() === today.toDateString()) return "오늘";
  return d.toLocaleDateString("ko-KR", { month: "long", day: "numeric" });
}
const grouped = computed(() => {
  const groups: { label: string; items: ConversationSummary[] }[] = [];
  for (const c of conversations.value) {
    const label = groupLabel(c.last_message_at);
    if (groups[groups.length - 1]?.label !== label) groups.push({ label, items: [] });
    groups[groups.length - 1].items.push(c);
  }
  return groups;
});

watch(id, async () => {
  stream.stop();
  error.value = "";
  evidence.value = null;
  drawer.value = false;
  await loadConversation();
  if (!id.value) await startNewWith((route.query.product as string) || session.products[0]?.id || "");
});
let searchTimer: number | undefined;
watch(search, () => { window.clearTimeout(searchTimer); searchTimer = window.setTimeout(loadList, 250); });

onMounted(async () => {
  await session.loadProducts();
  get<string[]>("/api/examples").then((x) => (examples.value = x)).catch(() => {});
  loadList();
  await loadConversation();
  if (!id.value) await startNewWith((route.query.product as string) || session.products[0]?.id || "");
});
</script>

<template>
  <div class="workspace">
    <!-- 왼쪽: 새 상담·검색·내 제품·이력 -->
    <aside class="sidebar" :class="{ open: drawer }">
      <RouterLink to="/consult" class="btn primary block"><Icon name="plus" />새 상담</RouterLink>
      <label class="field"><Icon name="search" /><input v-model="search" placeholder="상담 검색" aria-label="상담 검색" /></label>
      <div class="side-sec">
        <div class="section-title">내 제품 <RouterLink to="/products" class="muted" style="font-weight: 500">관리</RouterLink></div>
        <RouterLink v-for="p in session.products" :key="p.id" :to="{ path: '/consult', query: { product: p.id } }"
                    class="prod-mini" :class="{ on: product?.id === p.id }">
          <WashTower />
          <div><b>{{ p.nickname }}</b><span>{{ p.supported_model.series }} · 기억 {{ p.memory_count }}개</span></div>
        </RouterLink>
        <RouterLink v-if="!session.products.length" to="/products" class="btn sm soft">제품 등록하기</RouterLink>
      </div>
      <div class="side-sec" style="flex: 1; min-height: 0">
        <div class="section-title">상담 이력</div>
        <template v-for="g in grouped" :key="g.label">
          <div class="hist-group">{{ g.label }}</div>
          <RouterLink v-for="c in g.items" :key="c.id" :to="`/consult/${c.id}`" class="hist" :class="{ on: c.id === id }">
            <b>{{ c.title }}</b><span>{{ c.product_nickname }}</span>
          </RouterLink>
        </template>
        <p v-if="!conversations.length" class="muted" style="font-size: 12px; padding: 8px">{{ search ? "검색 결과가 없어요." : "아직 상담이 없어요." }}</p>
      </div>
      <p class="side-note"><Icon name="clock" :size="14" />상담 원문은 마지막 대화로부터 90일 동안 보관해요.</p>
    </aside>
    <div v-if="drawer" class="scrim" @click="drawer = false" />

    <!-- 가운데: 대화 -->
    <section class="center">
      <header class="conv-head">
        <button class="icon-btn drawer-btn" aria-label="메뉴" @click="drawer = true"><Icon name="menu" /></button>
        <template v-if="conv">
          <span class="conv-title">{{ conv.title }}</span>
          <span class="prod-chip"><WashTower :width="12" />{{ conv.product.nickname }}</span>
          <div style="margin-left: auto; display: flex; gap: 2px">
            <button class="btn sm ghost sheet-btn" @click="sheet = true"><Icon name="file" :size="14" />근거</button>
            <button class="icon-btn" title="제목 바꾸기" @click="renameConversation"><Icon name="pencil" /></button>
            <button class="icon-btn" title="상담 지우기" :disabled="running" @click="removeConversation"><Icon name="x" /></button>
          </div>
        </template>
        <span v-else class="conv-title">새 상담</span>
      </header>

      <div ref="threadEl" class="thread">
        <!-- 새 상담: 제품·기억 고르기 -->
        <template v-if="!conv">
          <div class="card new-card">
            <h2>어떤 제품을 상담할까요?</h2>
            <div class="prod-pick">
              <button v-for="p in session.products" :key="p.id" class="prod-mini" :class="{ on: newProductId === p.id }" @click="startNewWith(p.id)">
                <WashTower /><div><b>{{ p.nickname }}</b><span>{{ p.supported_model.series }}</span></div>
              </button>
            </div>
            <p v-if="!session.products.length" class="notice"><Icon name="info" />먼저 <RouterLink to="/products" style="text-decoration: underline">내 제품</RouterLink>에서 워시타워를 등록해 주세요.</p>
            <template v-if="newMemories.length">
              <h3>이번 상담에 쓸 기억</h3>
              <div class="mem-row">
                <button v-for="m in newMemories" :key="m.id" class="mem-chip" :class="{ on: newSelected.includes(m.id) }"
                        @click="newSelected = newSelected.includes(m.id) ? newSelected.filter((x) => x !== m.id) : [...newSelected, m.id]">
                  <span class="box"><Icon v-if="newSelected.includes(m.id)" name="check" :size="11" /></span>{{ m.symptom }} → {{ m.action }}
                </button>
              </div>
              <p class="muted help">체크를 빼도 기억은 지워지지 않아요. 이미 대화에서 말한 내용은 그대로 남아요.</p>
            </template>
            <h3>예시 질문</h3>
            <div class="examples">
              <button v-for="(q, i) in examples.slice(0, 5)" :key="i" class="btn sm" @click="text = q">{{ q.length > 34 ? q.slice(0, 34) + "…" : q }}</button>
            </div>
          </div>
        </template>

        <template v-else>
          <template v-for="m in conv.messages" :key="m.id">
            <div v-if="m.kind === 'question'" class="msg-user" :id="`m-${m.id}`">
              <div style="white-space: pre-wrap">{{ m.content }}</div>
            </div>
            <div v-else-if="m.kind === 'checklist_report'" class="msg-report" :id="`m-${m.id}`">
              <div class="rp-head"><Icon name="check" :size="14" />점검 결과를 알렸어요</div>
              <div style="white-space: pre-wrap">{{ m.content.replace(/^\[점검 결과\]\n/, "") }}</div>
            </div>
            <AnswerCard v-else :message="m" :items="itemsOf(m)" :latest="m.id === latestAnswer?.id" :locked="locked"
                        :active-page="evidence?.messageId === m.id ? evidence.page : null"
                        @cite="(p) => cite(m, p)" @bookmark="toggleBookmark(m)" @save-memory="memoryDialog = true" @report="report" />
          </template>

          <div v-if="running" class="card pending" aria-live="polite">
            <div class="stages">
              <template v-for="(s, i) in STAGES" :key="s.key">
                <span v-if="i" class="stage-sep" />
                <span class="stage" :class="{ now: stream.stage.value === s.key || (s.key === 'generating' && stream.stage.value === 'revising'), done: stream.seen.value.includes(s.key) && stream.stage.value !== s.key }">
                  <span v-if="stream.stage.value === s.key" class="dot" />{{ s.key === 'generating' && stream.stage.value === 'revising' ? STAGE_LABELS.revising : s.label }}
                </span>
              </template>
            </div>
            <div class="skeleton"><i style="width: 92%" /><i style="width: 78%" /><i style="width: 64%" /></div>
            <p class="pending-note"><Icon name="clock" :size="14" />설명서를 찾아 답변을 만드는 중이에요. 보통 10~40초 걸려요.</p>
          </div>
          <div v-else-if="failed" class="card pending">
            <p class="error-box"><Icon name="alert" />{{ error || "답변을 만들지 못했어요." }}</p>
            <button class="btn sm primary" style="margin-top: 10px" @click="retry"><Icon name="refresh" :size="14" />다시 시도</button>
          </div>
        </template>
      </div>

      <div class="composer">
        <div class="composer-inner">
          <div v-if="conv?.memories.length" class="mem-row" :class="{ locked }">
            <span class="mem-label"><Icon name="note" :size="14" />적용할 기억</span>
            <button v-for="m in conv.memories" :key="m.id" class="mem-chip" :class="{ on: m.selected }" :disabled="locked" @click="toggleMemory(m.id)">
              <span class="box"><Icon v-if="m.selected" name="check" :size="11" /></span>{{ m.symptom }} → {{ m.action }}
            </button>
          </div>
          <p v-if="error && !failed" class="error-box" style="margin-bottom: 8px"><Icon name="alert" />{{ error }}</p>
          <div class="input-box" :class="{ locked }">
            <textarea v-model="text" :disabled="locked" maxlength="2000" rows="2" aria-label="질문"
                      :placeholder="locked ? '답변이 끝나면 이어서 질문할 수 있어요.' : '증상이나 표시창의 오류코드를 알려주세요. (Enter 보내기, Shift+Enter 줄바꿈)'"
                      @keydown="onKey" />
            <button class="btn primary" :disabled="locked || !text.trim()" @click="send"><Icon :name="locked ? 'lock' : 'arrow-up'" />보내기</button>
          </div>
        </div>
      </div>
    </section>

    <!-- 오른쪽: 상담 상황·근거 PDF -->
    <aside class="aside" :class="{ open: sheet }">
      <button class="btn sm ghost sheet-btn" style="align-self: flex-end" @click="sheet = false"><Icon name="x" :size="14" />닫기</button>
      <section class="card status-card panel">
        <h3>현재 상담 상황</h3>
        <dl class="kv">
          <dt>제품</dt><dd>{{ product ? `${product.nickname} (${product.supported_model.series})` : "-" }}</dd>
          <template v-if="latestAnswer?.result">
            <dt>증상</dt><dd>{{ latestAnswer.result.symptom || "-" }}</dd>
            <dt>오류코드</dt><dd><span v-if="latestAnswer.result.error_code" class="code">{{ latestAnswer.result.error_code }}</span><span v-else class="empty">없음</span></dd>
            <dt>판단</dt><dd><RouteBadge :route="latestAnswer.result.route" /></dd>
            <dt>이유</dt><dd class="reason">{{ latestAnswer.result.reason }}</dd>
          </template>
          <template v-else><dt>증상</dt><dd class="empty">질문 후 표시돼요</dd><dt>판단</dt><dd class="empty">질문 후 표시돼요</dd></template>
        </dl>
      </section>
      <EvidencePanel :message="evidenceMessage" :page="evidence?.page ?? null" :past="!!evidence && evidence.messageId !== latestAnswer?.id"
                     @select="(p) => evidenceMessage && (evidence = { messageId: evidenceMessage.id, page: p })" @back="evidence = null" />
    </aside>
    <div v-if="sheet" class="scrim sheet-scrim" @click="sheet = false" />

    <MemoryDraftDialog v-if="memoryDialog && conv" :conversation-id="conv.id" @close="memoryDialog = false"
                       @saved="memoryDialog = false; loadConversation(false); session.loadProducts(); flash('기억을 저장했어요. 다음 상담부터 쓰여요.')" />
    <div v-if="toast" class="toast" role="status">{{ toast }}</div>
  </div>
</template>

<style scoped>
.new-card { padding: 20px; max-width: 820px; display: flex; flex-direction: column; gap: 12px; }
.new-card h2 { font-size: 16px; font-weight: 750; }
.new-card h3 { font-size: 13px; font-weight: 700; margin-top: 4px; }
.prod-pick { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 8px; }
.prod-pick .prod-mini { border: 1px solid var(--line); background: #fff; text-align: left; }
.prod-pick .prod-mini.on { border-color: var(--teal-600); background: var(--teal-50); }
.examples { display: flex; flex-wrap: wrap; gap: 6px; }
.examples .btn { white-space: normal; height: auto; min-height: 30px; padding: 5px 10px; text-align: left; }
.help { font-size: 12px; }
.sheet-scrim { display: none; }
@media (min-width: 768px) { .aside .sheet-btn { display: none; } }
@media (max-width: 767px) { .sheet-scrim { display: block; } }
</style>
