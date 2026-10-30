import { defineConfig } from "@playwright/test";

// 화면 검사: python tests/e2e_server.py(가짜 엔진 + 예시 데이터)를 띄운 뒤 빌드한 화면을 확인합니다.
export default defineConfig({
  testDir: "e2e",
  outputDir: "test-results/out",
  timeout: 60_000,
  workers: 1, // 같은 상담을 고치는 테스트가 있어 순서대로 돌립니다.
  expect: { timeout: 15_000 },
  use: { baseURL: "http://localhost:8001", channel: "chrome" },
  webServer: {
    command: "cd .. && .venv/bin/python tests/e2e_server.py",
    url: "http://localhost:8001/healthz",
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
