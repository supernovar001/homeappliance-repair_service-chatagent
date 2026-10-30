<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ApiError, patch, post, type Memory } from "../api";
import Icon from "./Icon.vue";

// 상담의 고객 발화로 기억 초안을 만들고, 고객이 확인·수정한 것만 '확인된 기억'으로 저장합니다.
const props = defineProps<{ conversationId: string }>();
const emit = defineEmits<{ close: []; saved: [] }>();
const OUTCOMES = ["해결됨", "해결되지 않음", "결과 미확인"];

const drafts = ref<(Memory & { keep: boolean })[]>([]);
const loading = ref(true);
const saving = ref(false);
const error = ref("");

onMounted(async () => {
  try {
    const r = await post<Memory[]>(`/api/conversations/${props.conversationId}/memory-drafts`);
    drafts.value = r.map((m) => ({ ...m, keep: true }));
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : "기억 초안을 만들지 못했어요.";
  } finally {
    loading.value = false;
  }
});

async function save() {
  saving.value = true;
  error.value = "";
  try {
    for (const d of drafts.value.filter((x) => x.keep)) {
      await patch(`/api/memories/${d.id}`, { symptom: d.symptom, action: d.action, outcome: d.outcome, confirm: true });
    }
    emit("saved");
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : "저장하지 못했어요.";
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div class="scrim" @click="emit('close')" />
  <div class="dialog" role="dialog" aria-modal="true" aria-labelledby="mem-title">
    <h2 id="mem-title">기억으로 저장</h2>
    <p class="desc">이 상담에서 직접 하신 조치와 결과를 정리했어요. 확인하고 고친 내용만 이 제품의 다음 상담에 쓰여요.</p>
    <p v-if="loading" class="muted">초안을 만드는 중이에요…</p>
    <p v-else-if="!drafts.length && !error" class="empty-box">직접 하신 조치를 찾지 못했어요.<br>상담에서 권장만 받은 조치는 기억으로 저장하지 않아요.</p>
    <div v-for="d in drafts" :key="d.id" class="draft" :class="{ off: !d.keep }">
      <label class="keep"><input v-model="d.keep" type="checkbox" />저장</label>
      <label>증상<input v-model="d.symptom" class="field" maxlength="200" /></label>
      <label>수행한 조치<input v-model="d.action" class="field" maxlength="300" /></label>
      <div class="lab">결과
        <div class="seg"><button v-for="o in OUTCOMES" :key="o" type="button" :class="{ on: d.outcome === o }" @click="d.outcome = o">{{ o }}</button></div>
      </div>
      <p class="quote"><Icon name="note" :size="13" />근거 발화: “{{ d.evidence }}”</p>
    </div>
    <p v-if="drafts.length" class="notice" style="margin-top: 10px"><Icon name="info" />상담에서 권장만 받고 하지 않은 조치는 초안에서 뺐어요.</p>
    <p v-if="error" class="error-box" style="margin-top: 10px"><Icon name="alert" />{{ error }}</p>
    <div class="acts">
      <button class="btn" @click="emit('close')">취소</button>
      <button class="btn primary" :disabled="saving || loading || !drafts.some((d) => d.keep)" @click="save">확인하고 저장</button>
    </div>
  </div>
</template>

<style scoped>
.draft { border: 1px solid var(--line); border-radius: 10px; padding: 12px; display: flex; flex-direction: column; gap: 8px; margin-top: 10px; font-size: 12.5px; color: var(--ink-2); font-weight: 600; }
.draft.off { opacity: .55; }
.draft label { display: flex; flex-direction: column; gap: 4px; }
.draft .keep { flex-direction: row; align-items: center; gap: 6px; }
.lab { display: flex; flex-direction: column; gap: 4px; }
.quote { font-weight: 500; font-size: 12px; color: var(--ink-3); display: flex; gap: 6px; align-items: flex-start; }
</style>
