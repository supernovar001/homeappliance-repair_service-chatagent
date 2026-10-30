<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { useSession } from "../stores/session";
import Icon from "./Icon.vue";

const session = useSession();
const route = useRoute();
const menu = ref(false);
watch(() => route.fullPath, () => (menu.value = false));
const initial = computed(() => (session.me?.name || session.me?.email || "?").slice(0, 1).toUpperCase());
const tabs = computed(() => [
  { to: "/consult", label: "상담", on: route.name === "consult" },
  { to: "/products", label: "내 제품", on: route.name === "products" },
  { to: "/bookmarks", label: "북마크", on: route.name === "bookmarks" },
  ...(session.me?.is_admin ? [{ to: "/admin", label: "관리자", on: route.name === "admin", admin: true }] : []),
]);
</script>

<template>
  <header class="topbar">
    <RouterLink to="/consult" class="brand">
      <span class="brand-mark"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.2"><rect x="4.5" y="3" width="15" height="18" rx="3" /><circle cx="12" cy="13.5" r="4.2" /><path d="M8 6.5h3" /></svg></span>
      워시케어
    </RouterLink>
    <nav class="nav">
      <RouterLink v-for="t in tabs" :key="t.to" :to="t.to" :class="{ on: t.on }">
        {{ t.label }}<span v-if="t.admin" class="admin-tag">관리</span>
      </RouterLink>
    </nav>
    <div class="top-right">
      <span class="who">{{ session.me?.name || session.me?.email }}</span>
      <img v-if="session.me?.picture" :src="session.me.picture" class="avatar" alt="" referrerpolicy="no-referrer" />
      <span v-else class="avatar">{{ initial }}</span>
      <button class="icon-btn mobile-menu" aria-label="메뉴" :aria-expanded="menu" @click="menu = !menu"><Icon name="more" /></button>
      <button class="icon-btn" title="로그아웃" @click="session.logout()"><Icon name="logout" /></button>
    </div>
    <nav v-if="menu" class="card mobile-nav">
      <RouterLink v-for="t in tabs" :key="t.to" :to="t.to" :class="{ on: t.on }">{{ t.label }}</RouterLink>
    </nav>
  </header>
</template>

<style scoped>
.topbar { position: relative; }
.mobile-menu { display: none; }
.mobile-nav { position: absolute; right: 12px; top: 52px; z-index: 70; display: flex; flex-direction: column; padding: 6px; min-width: 160px; box-shadow: 0 10px 30px rgba(15,23,42,.15); }
.mobile-nav a { padding: 9px 12px; border-radius: 7px; font-size: 13.5px; color: var(--ink-2); }
.mobile-nav a.on { background: var(--teal-50); color: var(--teal-800); font-weight: 650; }
@media (max-width: 767px) { .mobile-menu { display: inline-grid; } }
</style>
