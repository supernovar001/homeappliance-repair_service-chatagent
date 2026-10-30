<script setup lang="ts">
// 워시타워 일러스트(위: 건조기, 가운데: 조작부, 아래: 세탁기). 제품 사진이 없어 직접 그렸습니다.
withDefaults(defineProps<{ width?: number }>(), { width: 26 });
</script>

<template>
  <svg :width="width" :height="width * 1.5" viewBox="0 0 64 96" fill="none" stroke="currentColor" stroke-width="2.4" aria-hidden="true">
    <rect x="6" y="3" width="52" height="90" rx="8" fill="#fff" />
    <rect x="6" y="44" width="52" height="9" fill="currentColor" stroke="none" opacity=".12" />
    <path d="M6 44h52M6 53h52" stroke-width="1.6" />
    <rect x="12" y="47.3" width="15" height="2.6" rx="1.3" fill="currentColor" stroke="none" opacity=".6" />
    <circle cx="43" cy="48.6" r="1.6" fill="currentColor" stroke="none" />
    <circle cx="49" cy="48.6" r="1.6" fill="currentColor" stroke="none" />
    <circle cx="32" cy="23.5" r="12.5" />
    <circle cx="32" cy="23.5" r="7" fill="currentColor" stroke="none" opacity=".14" />
    <circle cx="32" cy="72.5" r="14.5" />
    <circle cx="32" cy="72.5" r="8.5" fill="currentColor" stroke="none" opacity=".18" />
  </svg>
</template>
