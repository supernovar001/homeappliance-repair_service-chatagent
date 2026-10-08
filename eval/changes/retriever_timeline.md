## 검색 방식 변경 이력: baseline → current → hybrid_code

검색 방식은 앞 단계의 기능을 유지한 채 하나씩 더해 왔습니다. 세 방식 모두 `app.py`의 `RETRIEVER_MODES`에 등록되어 있어, 같은 코드에서 검색 방식만 바꿔 비교할 수 있습니다(환경변수 `RETRIEVER_MODE`, 평가 스크립트 `--mode`).

```
10/02  ① baseline ─────────── 순수 벡터 검색                      커밋 2d39367
         │
10/02  ② current ──────────── + 오류코드 우선 규칙 + 1E 인식        커밋 9c2dcf6
         │
10/04  ②' current 보강 ─────── + 질문 오타 정규화
         │
10/04  ③ hybrid_code ──────── + BM25 키워드 검색 (RRF 결합)         현재 배포 기본값
```

### 단계별 변경점

#### ① baseline: 순수 벡터 RAG (커밋 `2d39367`)

- 설명서 PDF → 500자/100자 겹침 청킹(107개) → `text-embedding-3-small` 임베딩 → `InMemoryVectorStore`
- 질문 임베딩과의 코사인 유사도로 Top-8 청크를 고릅니다.
- **문제**: `IE`, `UE` 같은 짧은 오류코드를 임베딩이 구분하지 못합니다. 고객이 표시창의 `IE`를 `1E`로 읽고 질문하면 정답 문서(55쪽)가 7위로 밀립니다.

#### ② current: 오류코드 우선 규칙 (커밋 `9c2dcf6`)

| 구성 | 코드 위치 | 내용 |
|---|---|---|
| 오류코드 감지 | `CODE_PATTERN` | 질문에서 UE, IE, dE1 등 오류코드를 정규식으로 찾음 |
| 코드 → 안내 페이지 사전 | `ERROR_PAGES` | 코드별 안내 페이지 (예: `IE → 55·40쪽`) |
| 우선 배치 | `WasherManualRetriever` (`use_code_priority`) | 안내 페이지에서 코드가 적힌 청크를 Top-8 맨 앞에 두고, 남은 자리는 벡터 유사도 순으로 채움 |
| 1E 인식 | `CODE_PATTERN`, `ERROR_PAGES`, `CODE_TEXT_ALIASES` | `1E`를 패턴에 추가하고 `IE`·`1E`를 같은 코드로 묶음 (40쪽 원문 추출 표기도 `1E`) |

#### ②' current 보강: 질문 오타 정규화 (10/04)

- 검색 전에 `QUERY_TYPO_MAP` + `normalize_query()`로 질문 속 주요 키워드를 설명서 표기로 바꿉니다.
  - 오류코드: `1E → IE`, `0E → OE` (표시창의 I·O를 숫자로 읽는 경우)
  - 고장 증상: `냄세 → 냄새`, `쉰네 → 쉰내`, `고무페킹 → 고무패킹`, `거름만 → 거름망` (ㅐ/ㅔ 혼동 등 예상 오타)
- baseline을 제외한 모든 방식에 적용합니다(`use_query_normalization`). baseline은 기록된 수치와 비교할 수 있도록 질문을 그대로 검색합니다.
- 측정 영향은 거의 없습니다. 개발 평가셋 MRR은 정규화 전과 같은 0.92입니다. 1E는 ②에서 이미 처리되고 있었고, 증상 오타는 평가 질문에 포함되어 있지 않습니다.

#### ③ hybrid_code: BM25 + 벡터 하이브리드 (10/04)

| 구성 | 코드 위치 | 내용 |
|---|---|---|
| BM25 키워드 색인 | `bm25_tokens()`, `bm25_index` | 영문·숫자는 단어 그대로, 한글은 조사가 붙어도 겹치도록 2글자 단위로 토큰화 (`rank-bm25`) |
| 순위 결합 | `WasherManualRetriever._fuse_bm25()` | 벡터 순위와 BM25 순위를 Reciprocal Rank Fusion(`1/(60+순위)`)으로 합산 |
| 오류코드 우선 규칙 | ②와 동일 | 유지. 남은 자리를 하이브리드 순위로 채움 |
| 배포 기본값 | `RETRIEVER_MODE` | `current` → `hybrid_code` |

비교 실험용으로 오류코드 규칙 없이 하이브리드만 쓰는 `hybrid` 방식도 함께 등록했습니다.

### 단계별 성능

| 지표 | ① baseline | ② current | `hybrid` (참고) | ③ hybrid_code |
|---|---|---|---|---|
| 개발 평가셋 MRR (정답 문서가 있는 8문항) | 0.81 | 0.92 | 0.94 | 1.00 |
| **홀드아웃 MRR** (정답 근거 페이지가 있는 34문항) | **0.59** | **0.74** | **0.77** | **0.79** |
| 홀드아웃 근거 페이지 검색 (Top-8 포함) | 31/34 | 31/34 | 31/34 | 31/34 |
| 홀드아웃 범위 분류 (50문항) | 96% | 96% | - | 96% |
| 홀드아웃 상담 분류 (50문항, 1회 측정) | 84% | 86% | - | 90% |
| 홀드아웃 인용 유효성 (50문항) | 100% | 100% | - | 100% |
| 홀드아웃 실행 오류 | 0건 | 0건 | - | 0건 |
| `1E` 질문(개발 Q05) 정답 순위 | 7위 | 1위 | 1위 | 1위 |

- 홀드아웃: 개발에 쓰지 않은 50문항(`eval/holdout_50.json`). 오류코드 21 · 증상형 12 · 범위 외 7 · 안전 위험 4 · 프롬프트 인젝션 3 · 모호 3
- 홀드아웃 수치는 모두 10/04에 같은 코드에서 검색 방식만 바꿔 측정했습니다. 표의 차이는 검색 방식만의 효과입니다.

### 결과 해석

- **검색 MRR 0.59 → 0.74 → 0.79**: 검색 단계는 LLM을 쓰지 않아 다시 실행해도 같은 값이 나옵니다. 개발 평가셋(8문항)의 1.00은 평가셋이 작아 생긴 값이고, 홀드아웃에서는 0.79입니다.
- **근거 페이지 검색은 세 방식 모두 31/34**: 하이브리드는 새 정답을 찾아낸 것이 아니라, 이미 찾은 정답 문서의 순위를 올렸습니다.
- **상담 분류 84% → 86% → 90%**: 방향은 일관되지만 차이가 2~3문항이고, LLM 생성 변동(이전 3회 측정에서 약 2%p)과 겹칩니다. 검색 방식의 효과로 단정하려면 반복 측정이 필요합니다.
- **남은 실패(hybrid_code 6건)는 대부분 판단 단계의 문제**입니다. 정답 문서는 검색됐지만 상담 분류가 틀렸습니다. 예: FE(서비스 센터 안내 대상)에 자가 점검을 권함, 첫 시도인데 기사 점검을 권함(H10, H13, H28), 원인을 이미 특정한 문의를 범위 외로 분류(H04).

### 같은 기간의 검색 외 변경 (세 방식에 공통, 비교 수치에 영향 없음)

| 시점 | 변경 |
|---|---|
| `9c2dcf6` | 사용법 질문 통과(`is_usage_question`), IE 정의 프롬프트 규칙, IE 정의 검사와 고정 안내 문구 |
| 10/04 | PDF 로딩을 LangChain `PyPDFLoader`로 교체(정제 후 추출 텍스트·청크 동일), 상담 흐름을 5단계 LCEL 체인(`consult_flow`)으로 재구성, Docker 배포 구성(`Dockerfile`, 루트 `render.yaml`) |

### 재현 방법

```bash
# 검색 지표만 비교 (모든 방식, 임베딩 호출만)
python src/holdout_eval.py --retrieval-only

# 상담까지 포함한 홀드아웃 평가 (질문당 OpenAI 호출 2~3회) → results/holdout/*.csv
python src/holdout_eval.py --mode baseline
python src/holdout_eval.py --mode current
python src/holdout_eval.py --mode hybrid_code

# 개발 평가셋(10문항) 평가 → results/
python src/capstone_eval.py --mode hybrid_code
```

측정 결과 파일: `results/holdout/20261004_0755_holdout_baseline.csv`, `20261004_0750_holdout_current.csv`, `20261004_0750_holdout_hybrid_code.csv`

---

## 10/07~10/08: 검수 Markdown + Parent-Child + Qdrant + 재정렬 (`parent_rerank*`, `child_rerank_code`)

```
10/07  ④ parent_rerank_code ── 검수 Markdown · Parent-Child 청킹 · Qdrant(dense+BM25 → RRF) · Cross-encoder 재정렬
         │
10/08  ⑤ child_rerank_code ─── + 구어체 동의어 확장 + child 단위 재정렬 + 안전 경고 고정   현재 기본값
```

| 구성 | 코드 위치 | 내용 |
|---|---|---|
| PDF 직접 추출·검수 | `src/extract_pages.py` → `data/pages/p###.md` | PyMuPDF로 2단·표를 Markdown으로 추출한 뒤 사람이 원본 이미지와 대조해 40쪽 수정. 표시창 글꼴 오추출(dE2→`dEz`, IE→`1E`, CL→`[L`)과 17쪽 깨진 글자 정리 |
| Parent-Child 청킹 | `load_parents`, `child_documents` | parent = `#`·`##` 제목 섹션(1500자 초과 시 표의 같은 항목·문단 단위로 분할), child = 250자 조각 또는 표 한 행. parent 77개 / child 593개 |
| Qdrant 하이브리드 | `parent_child_index`, `ParentChildRetriever` | child마다 dense(OpenAI)·sparse(BM25, IDF는 Qdrant) 벡터 저장, 서버 내 RRF 결합. 로컬 파일 모드, 내용이 바뀔 때만 재색인 |
| 재정렬 | `reranker` | `BAAI/bge-reranker-v2-m3` Cross-encoder, Top-5 parent를 LLM에 전달 |
| 동의어 확장 | `QUERY_SYNONYMS`, `expand_query` | 시끄럽→소음, 흔들→진동, 김→증기, 쉰내→냄새 등(연기는 증기로 바꾸지 않음) |
| child 단위 재정렬 | `rerank_unit="child"` | parent 점수 = 가장 높은 child 점수. 증상 여러 개를 묶은 긴 parent의 점수 희석 방지, 검색 1.5초 → 0.8초 |
| 안전 경고 고정 | `SAFETY_TERMS`, `_safety_parents` | 연기·타는 냄새·감전 등 표현이 있으면 3~9쪽 안전 경고 parent를 최대 2개 앞에 둠('연기가 나요'가 57쪽 '증기, 고장 아님'에 밀리던 문제) |

### 홀드아웃 검색 결과 (정답 페이지가 있는 34문항)

| 방식 | 근거 검색 | MRR |
|---|---|---|
| hybrid_code | 31/34 | 0.79 |
| parent_rerank_code (검수 전 자동 추출) | 33/34 | 0.94 |
| parent_rerank_code (검수 후) | 33/34 | 0.96 |
| child_rerank_code | 34/34 | 1.00 |

- **child_rerank_code의 1.00은 낙관적인 값입니다.** 동의어 규칙을 홀드아웃 실패 문항(H25·H29)을 보고 만들었으므로, 홀드아웃은 더 이상 독립 검증셋이 아닙니다. 개발셋 10문항에서는 나빠진 문항이 없고, Q03(쉰내)이 새로 해결됐습니다.
- 반환 개수가 다릅니다(기존 청크 8개, 새 방식 parent 5개).

## 10/08: 원인 포함률 검사 (답변 패턴 하네스)

고장 표에서 같은 증상의 행 = 설명서 원인 목록입니다(예: UE 6개). 고객 증상의 원인을 답변이 모두 다루도록 코드로 검사합니다.

| 단계 | 코드 위치 | 내용 |
|---|---|---|
| 원인 목록 선택 | `symptom_causes` | 오류코드가 있으면 그 코드의 행, 없으면 재정렬 점수가 가장 높은 행의 증상(점수 ≥ `CAUSE_MIN_SCORE` 0.6). 원인 2개 이상만 |
| 생성에 전달 | `format_cause_list` | '설명서 원인 목록(모두 안내할 것)'을 참고 문서에 추가 |
| 검사·재생성 | `missing_causes`, `review_answer` | 그 원인만의 고유 핵심어가 답변(또는 고객 질문)에 없으면 빠진 원인으로 보고 피드백 재생성 |
| 최종 보완 | `regenerate` | 그래도 빠진 원인은 설명서 문장을 그대로 덧붙임 |
| 예외 | `cause_check_applies` | 기사 점검 권장, 작업을 불안해하는 고객, 연기·감전 등 위험 상황, FE·PE·tE·vs |

홀드아웃 상담 평가(`20261008_1926_holdout_child_rerank_code.csv`, 1회 측정):

| 지표 | hybrid_code (10/04) | child_rerank_code (10/08) |
|---|---|---|
| 범위 분류 | 48/50 | 48/50 |
| 상담 분류 | 45/50 | 47/50 |
| 인용 유효성 | 50/50 | 50/50 |
| 원인 포함률 (모델 답변, 보완 전) | - | 61/69 (88%), 검사 15문항 중 전부 포함 9문항 |

- 실패: H04·H10·H47(기존과 같음), H49('세탁기가 이상해요'에 자가 점검으로 답함, 신규). H13·H15·H28 해결.
- 원인 포함률 측정 뒤 판정 규칙을 보완했습니다(활용형 '얼어/얼었/동결', 고객이 이미 말한 원인). 저장된 답변으로 다시 채점하면 63/69(91%)이고, 이 규칙으로 상담을 다시 실행하지는 않았습니다.
