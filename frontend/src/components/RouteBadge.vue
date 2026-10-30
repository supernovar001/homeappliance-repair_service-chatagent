<script setup lang="ts">
import { computed } from "vue";
const props = defineProps<{ route: string }>();
const cls = computed(() => ({ "자가 점검 우선": "self", "서비스 기사 점검 권장": "tech", "추가 확인 필요": "more" }[props.route] || "out"));
</script>

<template>
  <span class="route" :class="cls"><i />{{ route }}</span>
</template>
