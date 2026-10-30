# 워시케어

워시타워 세탁기 사용설명서(MFL71831423 Rev.06)를 근거로 자가 점검을 안내하는 상담 서비스입니다.
Google로 로그인하면 제품별 상담 이력, 증상별 점검 체크리스트, 확인한 기억(Memory), 북마크를 쓸 수 있습니다.

- 상담 AI는 `app.py` 하나에 있습니다. 범위 분류 → 증상 분석 → 하이브리드 검색(Qdrant + BM25 → 재정렬) → 답변 생성 → 인용·안전 검사 순서로 동작합니다.
- 서비스는 그 위에 FastAPI(`backend/`), PostgreSQL, Vue 3 화면(`frontend/`)을 얹었습니다.
- 예전 Gradio 화면은 `/demo`에 그대로 있습니다(로그인 없이 동작, `APP_USERNAME`·`APP_PASSWORD`를 넣으면 비밀번호 창이 붙습니다).

`app.py`는 모듈로 나누지 않습니다. 평가 스크립트(`src/holdout_eval.py`, `src/capstone_eval.py`)가 `app.retriever`를 바꿔 끼워 검색 방식을 비교하기 때문입니다.

## 구성

```
app.py                  상담 AI (검색·상담 체인·체크리스트·기억 초안·안전 검사, Gradio 화면)
backend/                FastAPI 서비스
  main.py               진입점 (/api, /auth, /demo, /healthz, Vue 화면 제공)
  auth.py               Google 로그인(OIDC), 서버 세션, CSRF
  engine.py             app.py 연결 (테스트는 FakeEngine)
  jobs.py               상담 작업 실행(스레드), 진행 단계 이벤트
  checklist.py          체크리스트 저장·상태 승계
  retention.py          보관 기간(90일) 정리
  api/                  제품·상담·기억·북마크·관리자 API
migrations/             Alembic 마이그레이션 (지원 모델 2종·설명서 기본 데이터 포함)
frontend/               Vue 3 + TypeScript + Vite
tests/                  백엔드 테스트 (pytest, OpenAI 호출 없음)
docs/mockups/           화면 시안
docs/DEV_NOTES.md       개발 노트 (확인할 점·특이사항·설계 결정·평가 기록)
```

## 로컬 실행

필요한 것: Python 3.11 이상, Node 24, Docker(PostgreSQL용), OpenAI API 키, Google OAuth 클라이언트.

처음 한 번 준비합니다. `.env`는 `.env.example`을 복사해 값을 채웁니다(아래 표). DB는 localhost:5433에 뜹니다.

```bash
pip install -r requirements-dev.txt
(cd frontend && npm ci)
cp .env.example .env
docker compose up -d db
alembic upgrade head
```

터미널 두 개에서 각각 실행합니다. 백엔드는 시작할 때 검색 색인과 재정렬 모델을 불러와 20~30초 걸리고,
`Application startup complete`가 나오면 http://localhost:5173 에 접속합니다(Vite가 API를 8000으로 넘깁니다).

```bash
uvicorn backend.main:app --port 8000
```

```bash
cd frontend && npm run dev
```

zsh는 대화형 셸에서 `#`을 주석으로 처리하지 않으므로, 명령 뒤에 주석을 붙여 붙여넣으면 인자로 들어가 실패합니다.

로컬에서 Vite(5173)로 접속할 때는 `.env`에 `BASE_URL=http://localhost:5173`을 넣습니다. Google 로그인 콜백이 Vite를 거쳐 백엔드로 갑니다.

배포 이미지 그대로 확인하려면 `docker compose --profile web up --build` 후 http://localhost:8000 에 접속합니다.

## 환경변수

| 이름 | 필수 | 설명 |
|---|---|---|
| `OPENAI_API_KEY` | 필수 | 질문 1건마다 gpt-4o-mini를 2~3회 호출합니다 |
| `DATABASE_URL` | 필수 | `postgresql://…` (Railway는 `${{Postgres.DATABASE_URL}}`) |
| `BASE_URL` | 필수 | 서비스 주소. Google 로그인 콜백(`{BASE_URL}/auth/google/callback`)과 출처 검사에 씁니다 |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | 필수 | Google Cloud의 OAuth 웹 클라이언트 |
| `SESSION_SECRET` | 필수 | 로그인 중 state를 서명하는 임의의 긴 문자열 |
| `ADMIN_EMAILS` | 선택 | 관리자 화면을 볼 Google 이메일(쉼표로 여러 개) |
| `QDRANT_PATH` | 선택 | 검색 색인 위치. Railway에서는 볼륨 경로 `/data/qdrant` |
| `RETENTION_DAYS` | 선택 | 상담 원문 보관 기간(기본 90일) |
| `MAX_CONCURRENT_CONSULTS` | 선택 | 동시에 만드는 답변 수(기본 2) |
| `OPENAI_TIMEOUT` | 선택 | OpenAI 호출 하나의 제한 시간(기본 60초) |
| `TORCH_NUM_THREADS` | 선택 | 재정렬 모델의 CPU 스레드 수. 비우면 torch 기본값을 씁니다. 시작 로그의 "CPU … 컨테이너 한도 …"를 보고 한도에 맞춥니다 |
| `APP_USERNAME`, `APP_PASSWORD` | 선택 | `/demo` Gradio 화면의 비밀번호 |

## 테스트

```bash
docker compose up -d db
pytest                                  # 백엔드 (washcare_test DB를 새로 만듭니다)
(cd frontend && npm run build)          # 타입 검사 + 빌드
python src/holdout_eval.py --mode child_rerank_code   # 상담 AI 회귀 평가 (OpenAI 비용이 듭니다)
```

## Railway 배포

`main`에 올리면 Railway가 `Dockerfile`로 빌드해 배포합니다(`railway.json`, 헬스체크 `/healthz`).

1. 프로젝트에 PostgreSQL을 추가하고, 웹 서비스 변수에 `DATABASE_URL=${{Postgres.DATABASE_URL}}`을 넣습니다.
2. 웹 서비스에 Volume을 `/data`로 붙이고 `QDRANT_PATH=/data/qdrant`를 넣습니다. 볼륨이 붙은 서비스는 재배포할 때 잠깐 멈춥니다.
3. 나머지 변수(`BASE_URL`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `SESSION_SECRET`, `ADMIN_EMAILS`, `OPENAI_API_KEY`)를 넣습니다.
4. 웹 서비스 메모리는 4GB 이상을 권장합니다(재정렬 모델이 약 2GB를 씁니다).

Google Cloud에서는 OAuth 동의 화면(External, 범위 openid·email·profile)을 **프로덕션**으로 게시하고,
웹 클라이언트의 승인된 리디렉션 URI에 `{BASE_URL}/auth/google/callback`을 등록합니다. 등록할 URI는 3개입니다.

| 용도 | 승인된 리디렉션 URI |
|---|---|
| Railway 배포 | `https://homeappliance-repair-service-chatagent-production-c77d.up.railway.app/auth/google/callback` |
| 로컬 개발(Vite, `BASE_URL=http://localhost:5173`) | `http://localhost:5173/auth/google/callback` |
| 로컬 백엔드 단독(`BASE_URL=http://localhost:8000`) | `http://localhost:8000/auth/google/callback` |

`BASE_URL`과 등록한 URI의 주소가 한 글자라도 다르면 Google이 `redirect_uri_mismatch`로 거부합니다(끝의 `/`, http/https 포함).

## 개인정보와 보관

- 상담 원문은 마지막 대화로부터 90일 뒤 지웁니다. 확인한 기억은 남기고 출처 상담 연결만 끊습니다.
- 사용자가 상담을 지우면 그 상담에서 저장한 기억도 함께 지웁니다.
- 관리자는 상담 원문을 볼 수 있고, 열람할 때마다 감사 기록이 남습니다. 통계에는 개인정보가 없는 기록만 씁니다.

## 주의

- 자가 점검 안내는 해결을 보장하지 않으며, '서비스 기사 점검 권장'은 실제 방문 예약이 아닙니다.
- 워시타워 세탁기 전용입니다. 건조기·냉장고 등 다른 제품 문의는 답변하지 않습니다.
