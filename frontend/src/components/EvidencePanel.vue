<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { pageUrl, type Message } from "../api";
import Icon from "./Icon.vue";

const props = defineProps<{ message: Message | null; page: number | null; past: boolean }>();
const emit = defineEmits<{ select: [page: number]; back: [] }>();

const pages = computed(() => {
  const list = [...(props.message?.result?.evidence_pages || [])];
  if (props.page && !list.includes(props.page)) list.push(props.page);
  return list;
});
const current = computed(() => props.page ?? pages.value[0] ?? null);
// 답변의 근거 문단을 형광펜으로 표시한 페이지 이미지를 받습니다.
const src = computed(() => current.value && props.message ? `${pageUrl(current.value)}?message_id=${props.message.id}` : "");
const failed = ref(false);
watch(src, () => (failed.value = false));
</script>

<template>
  <section class="card ev-card panel">
    <h3><Icon name="file" :size="14" />{{ past ? "이전 답변의 근거" : "근거 페이지" }}
      <span class="sub">{{ message?.result?.evidence_basis || "" }}</span>
    </h3>
    <button v-if="past" class="btn sm soft" style="margin-bottom: 10px; align-self: flex-start" @click="emit('back')">
      <Icon name="arrow-left" :size="14" />최신 답변 근거로 돌아가기
    </button>
    <template v-if="current">
      <div class="page-tabs">
        <button v-for="p in pages" :key="p" class="pt" :class="{ on: p === current }" @click="emit('select', p)">PDF {{ p }}쪽</button>
      </div>
      <figure class="pdf">
        <a :href="src" target="_blank" rel="noopener" title="크게 보기">
          <img v-if="!failed" :src="src" :alt="`사용설명서 ${current}쪽`" loading="lazy" @error="failed = true" />
          <p v-else class="empty-box" style="margin: 10px">페이지를 불러오지 못했어요.</p>
        </a>
        <figcaption><span>사용설명서 {{ current }}쪽</span><span><Icon name="zoom" :size="13" /> 눌러서 크게 보기</span></figcaption>
      </figure>
      <p class="hl-legend"><i />답변이 근거로 쓴 부분</p>
    </template>
    <div v-else class="empty-box"><Icon name="file" />질문하면 답변이 근거로 쓴 설명서 페이지가 여기에 보여요.</div>
  </section>
</template>
