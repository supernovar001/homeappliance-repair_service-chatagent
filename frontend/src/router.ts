import { createRouter, createWebHistory } from "vue-router";
import { useSession } from "./stores/session";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "landing", component: () => import("./views/LandingView.vue"), meta: { public: true } },
    { path: "/consult/:id?", name: "consult", component: () => import("./views/ConsultView.vue") },
    { path: "/products", name: "products", component: () => import("./views/ProductsView.vue") },
    { path: "/bookmarks", name: "bookmarks", component: () => import("./views/BookmarksView.vue") },
    { path: "/admin", name: "admin", component: () => import("./views/AdminView.vue"), meta: { admin: true } },
    { path: "/:rest(.*)*", redirect: "/" },
  ],
});

// 로그인하지 않았으면 첫 화면으로, 관리자가 아니면 상담 화면으로 보냅니다(서버도 따로 권한을 검사합니다).
router.beforeEach(async (to) => {
  const session = useSession();
  if (!session.loaded) await session.load();
  if (to.meta.public) return session.me && to.name === "landing" ? { name: "consult" } : true;
  if (!session.me) return { name: "landing" };
  if (to.meta.admin && !session.me.is_admin) return { name: "consult" };
  return true;
});
