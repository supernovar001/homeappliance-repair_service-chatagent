<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";
import Icon from "../components/Icon.vue";
import WashTower from "../components/WashTower.vue";

const route = useRoute();
const loginError = computed(() => ({
  oauth: "Google 로그인을 마치지 못했습니다. 다시 시도해 주세요.",
  unverified: "이메일 인증이 끝난 Google 계정으로만 로그인할 수 있습니다.",
}[String(route.query.login_error || "")] || ""));
</script>

<template>
  <main class="landing">
    <section class="card hero">
      <span class="pic"><WashTower :width="56" /></span>
      <h1>워시케어</h1>
      <p class="lead">워시타워 사용설명서를 근거로 세탁기 증상을 함께 점검해 드려요.<br>제품별 상담 이력과 확인한 기억을 다음 상담에 이어서 씁니다.</p>
      <p v-if="loginError" class="error-box"><Icon name="alert" />{{ loginError }}</p>
      <a class="btn primary google" href="/auth/google/login">
        <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true"><path fill="#fff" d="M24 9.5c3.5 0 6.6 1.2 9 3.6l6.7-6.7C35.6 2.4 30.2 0 24 0 14.6 0 6.6 5.4 2.7 13.3l7.8 6C12.4 13.6 17.7 9.5 24 9.5z" opacity=".95"/><path fill="#fff" d="M46.1 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.4c-.5 2.9-2.2 5.3-4.6 7l7.4 5.7c4.3-4 6.9-9.9 6.9-17.2z" opacity=".8"/><path fill="#fff" d="M10.5 28.7c-.5-1.4-.8-3-.8-4.7s.3-3.2.8-4.7l-7.8-6C1 16.6 0 20.2 0 24s1 7.4 2.7 10.7l7.8-6z" opacity=".65"/><path fill="#fff" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.4-5.7c-2.1 1.4-4.8 2.2-8.5 2.2-6.3 0-11.6-4.2-13.5-9.9l-7.8 6C6.6 42.6 14.6 48 24 48z" opacity=".5"/></svg>
        Google 계정으로 시작하기
      </a>
      <ul class="facts">
        <li><Icon name="shield" />서비스 품질 관리를 위해 관리자가 상담 원문을 볼 수 있어요. 열람할 때마다 기록이 남아요.</li>
        <li><Icon name="clock" />상담 원문은 마지막 대화로부터 90일 동안 보관한 뒤 지워요. 확인한 기억은 남아요.</li>
        <li><Icon name="file" />안내는 사용설명서(MFL71831423 Rev.06)의 W10**N·W1310**N 시리즈 기준이에요.</li>
      </ul>
    </section>
  </main>
</template>

<style scoped>
.landing { flex: 1; display: grid; place-items: center; padding: 24px 16px; overflow-y: auto; }
.hero { width: min(480px, 100%); padding: 32px 28px; display: flex; flex-direction: column; align-items: center; gap: 14px; text-align: center; }
.pic { width: 96px; height: 120px; border-radius: 16px; background: var(--teal-50); display: grid; place-items: center; color: var(--teal-700); }
h1 { font-size: 24px; font-weight: 800; color: var(--teal-800); letter-spacing: -0.03em; }
.lead { color: var(--ink-2); font-size: 14px; }
.google { height: 44px; padding: 0 18px; font-size: 14px; width: 100%; }
.facts { list-style: none; display: flex; flex-direction: column; gap: 8px; text-align: left; font-size: 12.5px; color: var(--ink-2); margin-top: 6px; }
.facts li { display: flex; gap: 8px; align-items: flex-start; }
.facts .icon { margin-top: 2px; color: var(--teal-700); }
</style>
