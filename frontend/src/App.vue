<script setup lang="ts">
import TopBar from "./components/TopBar.vue";
import { useSession } from "./stores/session";
const session = useSession();
</script>

<template>
  <div class="app">
    <TopBar v-if="session.me" />
    <RouterView v-slot="{ Component }">
      <component :is="Component" />
    </RouterView>
  </div>
</template>
