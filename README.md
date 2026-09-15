---
title: 워시타워 세탁기 A/S 상담 도우미
emoji: 🧺
colorFrom: blue
colorTo: gray
sdk: gradio
sdk_version: 6.27.0
app_file: app.py
pinned: false
short_description: 세탁기 사용설명서를 근거로 자가 점검을 안내하는 LangChain RAG 상담 에이전트
---

# 워시타워 세탁기 A/S 상담 도우미

세탁기 사용설명서 PDF를 근거로 자가 점검 방법을 안내하고, 서비스 기사 점검이 필요한지 판단하는 LangChain RAG 에이전트입니다.
노트북 `세탁기_고장상담_QA_5개시나리오_LangChain.ipynb`의 상담 기능(1~5절, 12~13절)을 `app.py` 하나로 추출한 배포본입니다.

## 필요한 Secret

Space의 **Settings → Variables and secrets** 에 등록합니다.

| 이름 | 필수 | 설명 |
|---|---|---|
| `OPENAI_API_KEY` | 필수 | 질문 1건마다 gpt-4o-mini가 2~3회 호출됩니다 |
| `APP_USERNAME` | 선택 | 둘 다 등록하면 로그인 창이 생깁니다 |
| `APP_PASSWORD` | 선택 | 공개 Space의 API 비용을 막는 용도 |

## 구성 파일

```
app.py          상담 앱 (범위 분류 → 매뉴얼 검색 → 상담 체인 → 답변 검사 → UI)
requirements.txt
wachingmachine_service_manual.pdf   세탁기 서비스 매뉴얼 (검색 대상)
assets/         LangChain 구성도 이미지
```

## 로컬 실행

```bash
pip install -r requirements.txt
export OPENAI_API_KEY="sk-..."
python app.py            # http://127.0.0.1:7860
```

## 주의

- 자가 점검 안내는 해결을 보장하지 않으며, '서비스 기사 점검 권장'은 실제 방문 예약이 아닙니다.
- 워시타워 세탁기 전용입니다. 건조기·냉장고 등 다른 제품 문의는 답변하지 않습니다.
- 상담 이력은 브라우저 세션 메모리에만 유지되고 저장되지 않습니다.
