import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";

// AT-18: 390·768·1440px에서 주요 화면에 가로 넘침이 없는지 확인하고 스크린샷을 남깁니다.
const WIDTHS = [390, 768, 1440];
const conversationId = () => readFileSync("test-results/e2e-ids.txt", "utf-8").trim();
const PAGES = [
  { name: "consult", path: () => `/consult/${conversationId()}`, ready: "점검 체크리스트" },
  { name: "new-consult", path: () => "/consult", ready: "어떤 제품을 상담할까요?" },
  { name: "products", path: () => "/products", ready: "제품 등록" },
  { name: "bookmarks", path: () => "/bookmarks", ready: "이전 답변" },
  { name: "admin", path: () => "/admin", ready: "일별 완료 답변" },
];

test.beforeEach(async ({ context }) => {
  await context.addCookies([{ name: "wc_session", value: "e2e-admin-token", domain: "localhost", path: "/" }]);
});

for (const width of WIDTHS) {
  for (const p of PAGES) {
    test(`${p.name} @${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: width < 768 ? 844 : 900 });
      await page.goto(p.path());
      await expect(page.getByText(p.ready).first()).toBeVisible();
      await page.waitForLoadState("networkidle");
      const overflow = await page.evaluate(() => {
        const doc = document.documentElement;
        const wide = [...document.querySelectorAll<HTMLElement>("body *")]
          .filter((el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.right > doc.clientWidth + 1 && getComputedStyle(el).position !== "fixed"; })
          .filter((el) => !el.closest(".table-wrap, .sidebar, .aside"))
          .slice(0, 5).map((el) => `${el.tagName.toLowerCase()}.${el.className}`);
        return { scroll: doc.scrollWidth - doc.clientWidth, wide };
      });
      await page.screenshot({ path: `test-results/shots/${p.name}-${width}.png`, fullPage: false });
      expect(overflow.scroll, `가로 넘침: ${overflow.wide.join(", ")}`).toBeLessThanOrEqual(0);
      expect(overflow.wide).toEqual([]);
    });
  }
}

test("상담 화면에서 질문을 보내면 진행 단계 뒤 답변이 붙는다", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/consult/${conversationId()}`);
  await page.getByLabel("질문").fill("배수 호스 펴 놨는데 그래도 OE가 떠요");
  await page.getByRole("button", { name: "보내기" }).click();
  await expect(page.locator(".answer")).toHaveCount(2);
  await expect(page.locator(".msg-user")).toHaveCount(2);
  await expect(page.getByText("확인 완료").first()).toBeVisible();
});

test("근거 인용을 누르면 PDF 패널이 그 페이지를 보여 준다", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/consult/${conversationId()}`);
  await page.locator(".ans-body .cite").first().click();
  await expect(page.locator(".pdf img")).toHaveAttribute("src", /pages\/41\?message_id=/);
});
