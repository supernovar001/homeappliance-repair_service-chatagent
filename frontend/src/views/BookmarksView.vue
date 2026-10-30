<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { del, get } from "../api";
import Icon from "../components/Icon.vue";
import RouteBadge from "../components/RouteBadge.vue";
import WashTower from "../components/WashTower.vue";
import { useSession } from "../stores/session";

interface Bookmark {
  message_id: string; conversation_id: string; conversation_title: string; product_id: string; product_nickname: string;
  question: string; answer: string; route: string | null; evidence_pages: number[]; checklist_count: number; answered_at: string; saved_at: string;
}
const SIZE = 10;
const session = useSession();
const items = ref<Bookmark[]>([]);
const total = ref(0);
const page = ref(1);
const q = ref("");
const productId = ref("");
const pages = computed(() => Math.max(1, Math.ceil(total.value / SIZE)));

async function load() {
  const params = new URLSearchParams({ q: q.value, page: String(page.value), size: String(SIZE) });
  if (productId.value) params.set("product_id", productId.value);
  const r = await get<{ items: Bookmark[]; total: number }>(`/api/bookmarks?${params}`);
  items.value = r.items;
  total.value = r.total;
}
async function unbookmark(b: Bookmark) {
  await del(`/api/messages/${b.message_id}/bookmark`);
  await load();
}
function when(iso: string) { return new Date(iso).toLocaleString("ko-KR", { month: "long", day: "numeric", hour: "2-digit", minute: "2-digit" }); }
function body(answer: string) { return answer.replace(/^판단:[^\n]*\n이유:[^\n]*\n*/, "").replace(/\[PDF\s*\d+쪽\]/g, "").replace(/[#*>`]/g, ""); }

let timer: number | undefined;
watch(q, () => { window.clearTimeout(timer); timer = window.setTimeout(() => { page.value = 1; load(); }, 250); });
watch([productId, page], load);
onMounted(async () => { await session.loadProducts(); await load(); });
</script>

<template>
  <main class="page">
    <div class="wrap">
      <div class="page-head"><h1>북마크</h1><span class="desc">저장한 AI 답변 {{ total }}개</span></div>
      <div class="filters">
        <label class="field search"><Icon name="search" /><input v-model="q" placeholder="답변·질문 검색" aria-label="북마크 검색" /></label>
        <select v-model="productId" class="field" aria-label="제품">
          <option value="">모든 제품</option>
          <option v-for="p in session.products" :key="p.id" :value="p.id">{{ p.nickname }}</option>
        </select>
      </div>
      <p class="notice" style="margin-bottom: 14px"><Icon name="info" />북마크한 답변은 저장 당시의 안내예요. 지금 증상은 새 상담에서 다시 확인해 주세요.</p>

      <article v-for="b in items" :key="b.message_id" class="card bm">
        <div class="bm-head">
          <span class="past"><Icon name="clock" :size="14" />이전 답변 · {{ when(b.answered_at) }}</span>
          <RouteBadge v-if="b.route" :route="b.route" />
          <span class="prod"><WashTower :width="11" />{{ b.product_nickname }}</span>
          <div class="right">
            <button class="icon-btn on" title="북마크 해제" @click="unbookmark(b)"><Icon name="star-fill" /></button>
            <RouterLink :to="{ path: `/consult/${b.conversation_id}`, query: { m: b.message_id } }" class="btn sm soft">원래 상담으로 이동<Icon name="arrow-right" :size="14" /></RouterLink>
          </div>
        </div>
        <div class="q"><b>Q</b><span>{{ b.question }}</span></div>
        <div class="a"><b>A</b><p>{{ body(b.answer) }}</p></div>
        <div class="bm-foot">
          <span v-for="p in b.evidence_pages" :key="p" class="cite">PDF {{ p }}쪽</span>
          <span v-if="b.evidence_pages.length" class="sep" />
          <span>{{ b.checklist_count ? `점검 체크리스트 ${b.checklist_count}항목` : "체크리스트 없음" }}</span>
          <span class="sep" /><span>{{ when(b.saved_at) }} 저장</span>
        </div>
      </article>
      <div v-if="!items.length" class="empty-box">{{ q || productId ? "조건에 맞는 북마크가 없어요." : "답변 카드의 별표를 누르면 여기에 저장돼요." }}</div>

      <nav v-if="pages > 1" class="pager" aria-label="페이지">
        <button :disabled="page === 1" @click="page--"><Icon name="chev-left" :size="14" /></button>
        <button v-for="n in pages" :key="n" :class="{ on: n === page }" @click="page = n">{{ n }}</button>
        <button :disabled="page === pages" @click="page++"><Icon name="chev-right" :size="14" /></button>
      </nav>
    </div>
  </main>
</template>

<style scoped>
.wrap { max-width: 940px; margin: 0 auto; }
.filters { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
.filters .search { flex: 1; min-width: 200px; max-width: 360px; }
.bm { padding: 16px 18px; margin-bottom: 12px; }
.bm-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.past { display: inline-flex; align-items: center; gap: 5px; height: 24px; padding: 0 9px; border-radius: 999px; background: #f1f5f9; color: var(--ink-2); font-size: 12px; font-weight: 650; }
.prod { font-size: 12.5px; color: var(--ink-2); display: inline-flex; align-items: center; gap: 5px; }
.prod svg { color: var(--teal-700); }
.right { margin-left: auto; display: flex; align-items: center; gap: 6px; }
.q { margin-top: 12px; font-size: 13px; color: var(--ink-2); display: flex; gap: 8px; }
.q b { color: var(--ink-3); font-weight: 700; }
.a { margin-top: 6px; font-size: 13.5px; line-height: 1.65; display: flex; gap: 8px; }
.a b { color: var(--teal-700); font-weight: 700; }
.a p { display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.bm-foot { margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--line-2); display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--ink-3); flex-wrap: wrap; }
.sep { width: 3px; height: 3px; border-radius: 50%; background: #cbd5e1; }
.pager { display: flex; justify-content: center; gap: 6px; margin-top: 4px; }
.pager button { width: 32px; height: 32px; border-radius: 8px; display: grid; place-items: center; font-size: 13px; border: 1px solid var(--line); background: #fff; color: var(--ink-2); }
.pager button.on { background: var(--teal-700); border-color: var(--teal-700); color: #fff; font-weight: 650; }
@media (max-width: 767px) { .right { margin-left: 0; width: 100%; } }
</style>
