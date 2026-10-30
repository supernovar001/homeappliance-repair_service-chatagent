import { defineStore } from "pinia";
import { ApiError, get, post, setCsrf, type Me, type Product } from "../api";

// 로그인한 사용자와 내 제품 목록(여러 화면이 함께 씁니다).
export const useSession = defineStore("session", {
  state: () => ({ me: null as Me | null, loaded: false, products: [] as Product[] }),
  actions: {
    async load() {
      try {
        this.me = await get<Me>("/api/me");
        setCsrf(this.me.csrf_token);
      } catch (e) {
        if (!(e instanceof ApiError) || e.status !== 401) throw e;
        this.me = null;
      } finally {
        this.loaded = true;
      }
    },
    async loadProducts() {
      this.products = await get<Product[]>("/api/products");
      return this.products;
    },
    async logout() {
      await post("/auth/logout");
      this.me = null;
      location.href = "/";
    },
  },
});
