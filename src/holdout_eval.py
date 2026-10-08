# -*- coding: utf-8 -*-
"""홀드아웃 50문항(개발에 쓰지 않은 질문)으로 검색과 상담을 채점합니다.

LLM 평가자 없이 코드로만 판정합니다.
검색 지표(정답 근거 페이지가 있는 문항만):
- goldhit : 정답 근거 페이지가 Top-K에 포함됐는가
- MRR     : 첫 정답 근거 페이지 순위의 역수 평균
상담 지표(--retrieval-only가 아닐 때):
- scope_ok    : 제품 범위 분류가 정답과 일치하는가
- route_ok    : 상담 분류가 허용 분류 안에 드는가
- citation_ok : 답변이 인용한 페이지가 모두 실제 검색된 페이지인가
- 원인 포함률 : 고객 증상의 설명서 원인 중 모델 답변이 다룬 비율(검사 대상 문항만, 고정 문구 보완 전 기준)

  python src/holdout_eval.py --retrieval-only            # 모든 검색 방식의 검색 지표만 비교(임베딩 호출만)
  python src/holdout_eval.py --mode hybrid_code          # 상담까지 실행(질문당 OpenAI 호출 2~3회)
"""
import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
QUESTIONS_PATH = ROOT_DIR / "eval" / "holdout_50.json"
OUT_DIR = ROOT_DIR / "results" / "holdout"
sys.path.insert(0, str(ROOT_DIR))


def retrieval_marks(app, retriever, item):
    gold = set(item["reference_pages"])
    if not gold:
        return {"goldhit": None, "rr": None, "first_rank": None}
    pages = [doc.metadata["page"] for doc in retriever.invoke(item["question"])]
    first = next((i for i, p in enumerate(pages, 1) if p in gold), None)
    return {"goldhit": first is not None, "rr": 1 / first if first else 0.0, "first_rank": first}


def summarize_retrieval(rows):
    scored = [r for r in rows if r["goldhit"] is not None]
    hits = sum(r["goldhit"] for r in scored)
    mrr = sum(r["rr"] for r in scored) / len(scored)
    return hits, len(scored), mrr


def run_retrieval_only(app, questions):
    print(f"\n홀드아웃 {len(questions)}문항 검색 비교 (정답 근거 페이지가 있는 문항만, Top-K {app.TOP_K})")
    print(f"{'검색 방식':<14}{'근거 검색':>10}{'MRR':>8}   1위가 아닌 문항(순위)")
    for mode in app.RETRIEVER_MODES:
        retriever = app.build_retriever(mode)
        rows = [{"id": q["id"], **retrieval_marks(app, retriever, q)} for q in questions]
        hits, total, mrr = summarize_retrieval(rows)
        misses = [f"{r['id']}({r['first_rank'] or '-'})" for r in rows if r["goldhit"] is not None and r["first_rank"] != 1]
        print(f"{mode:<14}{f'{hits}/{total}':>10}{mrr:>8.2f}   {' '.join(misses) or '없음'}")


def run_full(app, mode, questions):
    import pandas as pd

    app.retriever = app.build_retriever(mode)  # retrieve()·consult()가 모듈 전역 retriever를 씁니다.
    rows = []
    for n, item in enumerate(questions, 1):
        marks = retrieval_marks(app, app.retriever, item)
        try:
            result = app.consult(item["question"], [])
        except Exception as error:
            print(f"[{n:2}/{len(questions)}] {item['id']} 오류: {type(error).__name__}: {error}")
            rows.append({"id": item["id"], "category": item["category"], "error": f"{type(error).__name__}: {error}", **marks})
            continue
        cited = set(map(int, re.findall(r"\[PDF\s*(\d+)쪽\]", result["answer"])))
        row = {
            "id": item["id"], "category": item["category"], "question": item["question"],
            "expected_scope": item["expected_scope"], "scope": result.get("scope"),
            "acceptable_routes": " | ".join(item["acceptable_routes"]), "route": result["route"],
            "retrieved_pages": result["retrieved_pages"], "reference_pages": item["reference_pages"],
            "answer": result["answer"], "trap": item["trap"],
            "scope_ok": result.get("scope") == item["expected_scope"],
            "route_ok": result["route"] in item["acceptable_routes"],
            # 인용이 없는 것은 위반이 아닙니다(범위 외 안내 등). 인용했다면 검색된 페이지여야 합니다.
            "citation_ok": cited <= set(result["retrieved_pages"]),
            "cause_check": result.get("cause_check", False),
            "causes_total": len(result.get("causes", [])) if result.get("cause_check") else 0,
            "causes_missed": len(result.get("causes_missed_by_model", [])),
            "causes_missed_list": " / ".join(result.get("causes_missed_by_model", [])),
            **marks,
        }
        rows.append(row)
        flags = "".join("✅" if row[k] else ("–" if row[k] is None else "❌") for k in ("scope_ok", "route_ok", "citation_ok", "goldhit"))
        print(f"[{n:2}/{len(questions)}] {item['id']} {flags}  {result['route']:<12} {item['question'][:28]}")

    df = pd.DataFrame(rows)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{datetime.now():%Y%m%d_%H%M}_holdout_{mode}.csv"
    df.to_csv(path, index=False, encoding="utf-8-sig")

    errors = int(df["error"].notna().sum()) if "error" in df.columns else 0
    ok = df[df["error"].isna()] if "error" in df.columns else df
    print("\n" + "=" * 58)
    print(f"검색 방식: {mode} — {app.RETRIEVER_MODES[mode]}")
    print(f"{'지표':<14}{'정답/전체':>12}{'정확도':>10}")
    print("-" * 58)
    for key, label in [("scope_ok", "범위 분류"), ("route_ok", "상담 분류"), ("citation_ok", "인용 유효성")]:
        hit = int(ok[key].sum())
        print(f"{label:<14}{f'{hit}/{len(ok)}':>12}{hit / len(ok):>9.0%}")
    hits, total, mrr = summarize_retrieval(rows)
    print(f"{'근거 페이지 검색':<14}{f'{hits}/{total}':>12}{hits / total:>9.0%}")
    print(f"{'검색 MRR':<14}{'':>12}{mrr:>10.2f}")
    checked = ok[ok["cause_check"]] if "cause_check" in ok.columns else ok.iloc[0:0]
    if len(checked):
        total, missed = int(checked["causes_total"].sum()), int(checked["causes_missed"].sum())
        full = int((checked["causes_missed"] == 0).sum())
        print(f"{'원인 포함률':<14}{f'{total - missed}/{total}':>12}{(total - missed) / total:>9.0%}   (검사 {len(checked)}문항 중 전부 포함 {full}문항)")
    print(f"실행 오류: {errors}건")
    fails = ok[~ok["scope_ok"] | ~ok["route_ok"] | ~ok["citation_ok"]]
    if len(fails):
        print(f"\n실패 {len(fails)}건")
        for _, r in fails.iterrows():
            bad = [n for n, k in [("범위", "scope_ok"), ("분류", "route_ok"), ("인용", "citation_ok")] if not r[k]]
            print(f"  {r['id']} [{','.join(bad)}] {r['route']} ← 기대 {r['acceptable_routes']} / 함정: {r['trap']}")
    print(f"\n저장: {path.relative_to(ROOT_DIR)}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="hybrid_code", help="app.RETRIEVER_MODES의 이름")
    parser.add_argument("--retrieval-only", action="store_true", help="모든 검색 방식의 검색 지표만 비교")
    args = parser.parse_args()
    import app
    questions = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    if args.retrieval_only:
        run_retrieval_only(app, questions)
    else:
        if args.mode not in app.RETRIEVER_MODES:
            sys.exit(f"지원하지 않는 검색 방식: {args.mode} (가능: {', '.join(app.RETRIEVER_MODES)})")
        run_full(app, args.mode, questions)


if __name__ == "__main__":
    main()
