# -*- coding: utf-8 -*-
"""검색·답변 평가 스크립트 (14.5 Baseline 결과 측정과 기록)

eval/questions.json의 질문을 한 가지 검색 방식으로 실행하고, 질문별로
질문 / 검색 Top-K 문서 / 정답 문서 포함 여부 / 최종 답변 / 문서 근거 여부 / 문제점
을 eval/results/에 기록합니다.

  python eval/run_eval.py --mode baseline
  python eval/run_eval.py --mode current
  (개선 방식을 추가하면) python eval/run_eval.py --mode hybrid
  비교: python eval/compare.py eval/results/<baseline>.json eval/results/<개선>.json

검색 방식은 app.py의 RETRIEVER_MODES / build_retriever에 등록합니다(배포의 RETRIEVER_MODE와 같은 이름).
개선 전략(MMR, BM25/Hybrid, MultiQuery, Reranker 등)을 적용한 검색기를 거기에 추가하면
같은 질문 집합으로 비교할 수 있습니다.

문항별로 답변이 인용한 PDF 페이지를 캡처해 첨부합니다(results/captures/<결과 이름>/).
캡처에는 그 문항에서 검색되어 모델에 전달된 청크가 노란 형광펜으로 표시되어,
답변 내용이 실제 근거에 있는지 대조할 수 있습니다.
"""
import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(EVAL_DIR.parent))
app = None  # main()에서 불러옵니다. import 시점에 색인 생성(임베딩 호출)이 실행되므로 --render에서는 불러오지 않습니다.
PDF_PATH = next(EVAL_DIR.parent.glob("*.pdf"), None)
CAPTURE_ZOOM = 1.3        # 인용 페이지
CAPTURE_ZOOM_OTHER = 1.0  # 검색됐지만 인용되지 않은 페이지(용량 절약)

NO_EVIDENCE_RE = re.compile(r"(설명서|매뉴얼)[^.\n]{0,20}(없|나와 있지|포함되어 있지|포함된 정보가 아닙)|확인할 수 없|확인이 어렵|안내되어 있지 않")
FABRICATED_RE = re.compile(r"\d+\s*(년|개월|원|만\s*원)")
LOW_RANK = 3        # 첫 정답 순위가 이보다 뒤면 '순위 낮음'으로 봅니다.
DUP_RATIO = 0.5     # 검색 청크 중 서로 다른 페이지 비율이 이 값 이하이면 '비슷한 청크 반복'으로 봅니다.

# 14.6 검색 품질 개선 전략 표: 관찰된 문제 → 우선 검토할 방법
STRATEGIES = {
    "duplicate": ("비슷한 Chunk만 반복 검색됨", "MMR"),
    "keyword": ("코드·약어·제품명이 잘 검색되지 않음", "BM25 / Hybrid / Ensemble"),
    "context": ("작은 Chunk는 잘 찾지만 문맥이 부족함", "ParentDocumentRetriever"),
    "phrasing": ("질문 표현에 따라 검색 결과가 크게 달라짐", "MultiQuery / Query Rewrite"),
    "order": ("후보 문서는 찾지만 순서가 좋지 않음", "Reranker"),
    "decompose": ("복합 질문의 하위 주제 일부를 찾지 못함", "MultiQuery / Query Decomposition"),
    "flow": ("검색과 무관하게 답변이 생성되지 않음", "상담 흐름(범위 분류) 수정 — 검색 전략 대상 아님"),
    "grounding": ("검색은 됐지만 답변 근거·인용이 부적합", "LongContextReorder / 프롬프트 인용 규칙"),
    "no_evidence": ("문서에 없는 질문에 근거 없음을 밝히지 못함", "Agentic RAG(검색 실패 판단) / 프롬프트"),
}


def evaluate(item, docs, result):
    """질문 하나의 검색·답변 결과를 14.5 기록 항목으로 정리하고 문제점을 진단합니다."""
    pages = [d["page"] for d in docs]
    groups = item["required_groups"]
    relevant = {p for group in groups for p in group}
    found = [any(p in pages for p in group) for group in groups]
    first_rank = next((i for i, p in enumerate(pages, 1) if p in relevant), None)
    answer = result["answer"]
    cited = sorted(app.cited_pages(answer))
    answered = bool(result["retrieved_pages"])  # 범위 밖·증상 되묻기 경로는 검색 없이 끝납니다.

    if item.get("expect_no_evidence"):
        hit = None
        grounded = bool(NO_EVIDENCE_RE.search(answer)) and not FABRICATED_RE.search(answer)
        grounding_note = "근거 없음을 밝힘" if grounded else "근거 없음을 밝히지 않았거나 수치를 지어냄"
    else:
        hit = all(found)
        grounded = answered and bool(cited) and set(cited) <= relevant
        if not answered:
            grounding_note = "답변 미생성(검색 없이 종료)"
        elif not cited:
            grounding_note = "인용 없음"
        else:
            outside = sorted(set(cited) - relevant)
            grounding_note = f"인용 {cited}" + (f" 중 정답 밖 페이지 {outside}" if outside else " 모두 정답 문서 안")

    problems = []
    if not answered and not item.get("expect_no_evidence"):
        problems.append(("flow", f"검색은 됐으나 상담 흐름에서 답변 없이 종료(판단: {result['route']})"))
    if hit is False:
        missing = ", ".join("/".join(f"{p}쪽" for p in groups[i]) for i, ok in enumerate(found) if not ok)
        key = "decompose" if len(groups) > 1 else ("keyword" if "키워드" in item["type"] else "phrasing")
        problems.append((key, f"정답 문서 누락: {missing} 미검색"))
    elif first_rank and first_rank > LOW_RANK:
        key = "keyword" if "키워드" in item["type"] else "order"
        problems.append((key, f"정답 문서 순위 낮음({first_rank}위)"))
    if docs and len(set(pages)) / len(docs) <= DUP_RATIO:
        problems.append(("duplicate", f"Top-{len(docs)} 중 서로 다른 페이지 {len(set(pages))}개뿐"))
    if answered and not grounded and not item.get("expect_no_evidence") and hit:
        problems.append(("grounding", grounding_note))
    if item.get("expect_no_evidence") and not grounded:
        problems.append(("no_evidence", grounding_note))

    return {
        "id": item["id"], "type": item["type"],
        "top_k": [{"rank": i, "chunk_id": d["chunk_id"], "page": d["page"], "score": round(d["score"], 3), "text": d["text"]} for i, d in enumerate(docs, 1)],
        "retrieved_pages": list(dict.fromkeys(pages)),
        "hit": hit, "group_recall": round(sum(found) / len(groups), 2) if groups else None, "first_rank": first_rank,
        "route": result["route"], "answer": answer, "cited_pages": cited, "answered": answered,
        "grounded": grounded, "grounding_note": grounding_note,
        "problems": [{"key": k, "detail": d} for k, d in problems],
    }


def run(mode, questions):
    app.retriever = app.build_retriever(mode)  # retrieve()·consult()가 모듈 전역 retriever를 씁니다.
    docs = [app.retrieve(q["question"]) for q in questions]
    with ThreadPoolExecutor(5) as ex:
        results = list(ex.map(app.consult, [q["question"] for q in questions]))
    return [evaluate(q, d, r) for q, d, r in zip(questions, docs, results)]


def _highlight_rects(page, text):
    """청크 본문이 페이지 어디에 있는지 찾아 사각형 목록을 돌려줍니다.
    PDF 추출 텍스트와 화면 배치(표의 줄바꿈, 왼쪽 열 코드)가 달라 청크 전체를 한 번에 찾을 수 없으므로
    3어절 창을 한 어절씩 밀며 찾고, 여러 곳에서 나오는 흔한 문구는 한 곳에서만 나오는 문구들이 정한
    세로 범위 안의 것만 씁니다."""
    words = text.split()
    windows = [" ".join(words[i:i + 3]) for i in range(max(1, len(words) - 2))]
    found = [page.search_for(w) for w in windows if len(w) >= 4]
    unique = [r[0] for r in found if len(r) == 1]
    if not unique:
        return [rect for rects in found for rect in rects]
    top, bottom = min(r.y0 for r in unique) - 15, max(r.y1 for r in unique) + 15
    return [rect for rects in found for rect in rects if top <= rect.y0 and rect.y1 <= bottom]


def capture_pages(rows, out_dir):
    """문항별로 근거 페이지(인용 페이지 + 검색된 모든 페이지)를 캡처하고,
    그 문항에서 검색된 해당 페이지 청크를 형광펜으로 표시합니다."""
    import pymupdf
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.png"):  # 다시 만들 때 이전 캡처가 섞이지 않게 지웁니다.
        old.unlink()
    with pymupdf.open(str(PDF_PATH)) as pdf:
        for r in rows:
            r["captures"] = []
            pages = list(dict.fromkeys(r["cited_pages"] + r["retrieved_pages"]))
            for page_no in pages:
                cited = page_no in r["cited_pages"]
                page = pdf[page_no - 1]
                chunks = [d for d in r["top_k"] if d["page"] == page_no]
                for d in chunks:
                    rects = _highlight_rects(page, d.get("text", ""))
                    if rects:
                        page.add_highlight_annot(rects)
                name = f"{r['id']}_p{page_no}.png"
                zoom = CAPTURE_ZOOM if cited else CAPTURE_ZOOM_OTHER
                page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), annots=True).save(str(out_dir / name))
                for annot in list(page.annots() or []):  # 다음 캡처에 표시가 남지 않게 지웁니다.
                    page.delete_annot(annot)
                r["captures"].append({"page": page_no, "cited": cited, "file": f"{out_dir.parent.name}/{out_dir.name}/{name}",
                                      "chunks": [d["chunk_id"] for d in chunks]})


def mark(value):
    return "-" if value is None else ("O" if value else "X")


def ratio(values):
    values = [v for v in values if v is not None]
    return f"{sum(values)}/{len(values)}" if values else "-"


def cell(text):
    """표 칸 안에서 줄바꿈과 | 가 표를 깨지 않도록 바꿉니다."""
    return text.replace("|", "\\|").replace("\n\n", "<br>").replace("\n", "<br>")


def to_markdown(meta, questions, rows):
    """14.5 양식(질문 | 검색 Top-K 문서 | 정답 문서 포함 여부 | 최종 답변 | 문서 근거 여부 | 문제점)으로 기록합니다."""
    mode, label = meta["mode"], meta["label"]
    scored = [r for r in rows if r["hit"] is not None]
    mrr = sum(1 / r["first_rank"] if r["first_rank"] else 0 for r in scored) / max(1, len(scored))
    lines = [
        f"# Baseline 결과 기록: {label}" if mode == "baseline" else f"# 평가 결과 기록: {label}", "",
        f"- 검색 방식: `{mode}` — {meta.get('description', '')}",
        f"- 실행 시각: {meta.get('run_at', '-')}",
        f"- 설정: 청크 {meta['chunk_size']}자 / 겹침 {meta['chunk_overlap']}자 · Top-K {meta['top_k']} · 임베딩 {meta.get('embedding_model', '-')} · 답변 모델 {meta.get('answer_model', '-')}",
        f"- 질문 수: {len(questions)}", "",
        "## 요약", "",
        "| 정답 문서 포함 | MRR | 문서 근거 있는 답변 |", "|---|---|---|",
        f"| {ratio([r['hit'] for r in rows])} | {mrr:.2f} | {ratio([r['grounded'] for r in rows])} |", "",
        "- 정답 문서 포함: 정답 페이지를 Top-K 안에서 찾은 질문 수. 복합 질문은 하위 주제를 모두 찾아야 포함. 문서에 없는 질문은 제외.",
        "- MRR: 첫 정답 문서 순위의 역수 평균(1에 가까울수록 정답이 앞에 옴).",
        "- 문서 근거 있는 답변: 인용이 있고 모두 정답 문서 안이면 O. 문서에 없는 질문은 '근거 없음'을 밝히고 수치를 지어내지 않으면 O. 답변이 질문의 모든 부분에 답했는지는 보지 않으므로 문제점 열의 [검토] 항목과 함께 봅니다.",
    ]
    verdicts = [r.get("verdict") for r in rows if r.get("verdict")]
    if verdicts:
        lines.append(f"- 답변 수동 검토: 제대로 {verdicts.count('O')} · 부분 {verdicts.count('△')} · 실패 {verdicts.count('X')} (질문 {len(verdicts)}개)")
    lines += ["", "## 질문별 기록", "",
              "| 질문 | 검색 Top-K 문서 | 정답 문서 포함 여부 | 최종 답변 | 문서 근거 여부 | 문제점 |",
              "|---|---|---|---|---|---|"]
    for q, r in zip(questions, rows):
        relevant = " + ".join("/".join(f"{p}쪽" for p in g) for g in q["required_groups"])
        question = f"**{q['id']}** {q['type']}<br>{q['question']}"
        top_k = "<br>".join(f"{d['rank']}. {d['page']}쪽 `{d['chunk_id']}` ({d['score']:.3f})" for d in r["top_k"])
        if r["hit"] is None:
            hit = "- (문서에 없는 질문)"
        else:
            hit = (f"O (첫 정답 {r['first_rank']}위)" if r["hit"] else f"X (재현율 {r['group_recall']})") + f"<br>정답: {relevant}"
        verdict = f"<br>**검토: {r['verdict']}**" if r.get("verdict") else ""
        grounded = f"{mark(r['grounded'])}<br>{r['grounding_note']}"
        if r.get("captures"):
            grounded += f"<br>[근거 캡처 보기](#evidence-{q['id'].lower()})"
        problems = [f"{p['detail']} → {STRATEGIES[p['key']][1]}" for p in r["problems"]]
        problems += [f"[검토] {note}" for note in r.get("review", [])]
        lines.append("| " + " | ".join([question, top_k, hit, cell(r["answer"]) + verdict, grounded, "<br>".join(cell(x) for x in problems) or "없음"]) + " |")

    counts = {}
    for r in rows:
        for p in r["problems"]:
            counts.setdefault(p["key"], []).append(r["id"])
    lines += ["", "## 문제 진단 → 우선 검토할 개선 방법 (14.6)", ""]
    if counts:
        lines += ["| 관찰된 문제 | 해당 질문 | 우선 검토할 방법 |", "|---|---|---|"]
        for key, ids in sorted(counts.items(), key=lambda kv: -len(kv[1])):
            lines.append(f"| {STRATEGIES[key][0]} | {', '.join(ids)} | {STRATEGIES[key][1]} |")
    else:
        lines.append("관찰된 문제가 없습니다.")

    lines += ["", "## 문항별 근거 문서 (PDF 캡처 · 청크 원문, 크로스체크용)", "",
              "- **검색된 청크 원문**: 그 문항에서 검색된 Top-K 청크 본문 전체입니다. 답변 생성 시 모델에 전달된 문맥과 같습니다.",
              "- **PDF 캡처**: 노란 형광펜이 검색된 청크 위치입니다. 답변이 인용한 페이지를 먼저 보이고, 검색됐지만 인용되지 않은 페이지는 접어 두었습니다.",
              "- 답변의 각 문장이 형광펜 부분에 있는지 대조하세요. 형광펜 밖 내용을 말하거나 형광펜 없는 페이지를 인용했다면 근거가 불명확한 것입니다.", ""]
    for q, r in zip(questions, rows):
        cited_set = set(r["cited_pages"])
        lines += [f'<a id="evidence-{q["id"].lower()}"></a>', "", f"### {q['id']} · {q['question']}", "",
                  f"**답변** (판단: {r['route']})", ""]
        lines += [f"> {line}" if line else ">" for line in r["answer"].splitlines()]
        lines.append("")
        if r.get("answered") is False:
            lines += ["※ 이 문항은 상담 흐름에서 검색 없이 종료되어, 아래 청크는 평가용으로 같은 질문을 검색한 결과이며 모델에는 전달되지 않았습니다.", ""]
        lines += [f"<details open><summary><b>검색된 Top-{len(r['top_k'])} 청크 원문</b></summary>", "",
                  "| 순위 | 청크 | 페이지 | 유사도 | 답변 인용 | 본문 |", "|---|---|---|---|---|---|"]
        for d in r["top_k"]:
            lines.append(f"| {d['rank']} | `{d['chunk_id']}` | {d['page']}쪽 | {d['score']:.3f} | {'O' if d['page'] in cited_set else '-'} | {cell(d.get('text', ''))} |")
        lines += ["", "</details>", ""]
        caps = r.get("captures", [])
        cited_caps = [c for c in caps if c["cited"]]
        other_caps = [c for c in caps if not c["cited"]]
        if cited_caps:
            lines += ["**답변이 인용한 페이지**", ""]
            for cap in cited_caps:
                marked = ", ".join(f"`{c}`" for c in cap["chunks"]) or "없음 — 검색되지 않은 페이지를 인용(모델이 받지 않은 근거)"
                lines += [f"PDF {cap['page']}쪽 · 형광펜 청크: {marked}", "", f"![PDF {cap['page']}쪽]({cap['file']})", ""]
        else:
            lines += ["**답변이 인용한 페이지**: 없음" + (" (문서에 없는 질문)" if r["hit"] is None else ""), ""]
        if other_caps:
            other_pages = ", ".join(f"{c['page']}쪽" for c in other_caps)
            lines += [f"<details{'' if cited_caps else ' open'}><summary><b>검색됐지만 인용되지 않은 페이지 {len(other_caps)}개</b> ({other_pages})</summary>", ""]
            for cap in other_caps:
                lines += [f"PDF {cap['page']}쪽 · 형광펜 청크: {', '.join(f'`{c}`' for c in cap['chunks'])}", "", f"![PDF {cap['page']}쪽]({cap['file']})", ""]
            lines += ["</details>", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="baseline", help="app.RETRIEVER_MODES의 이름(baseline, current, ...)")
    parser.add_argument("--label", help="결과 파일 이름(기본: 검색 방식 이름)")
    parser.add_argument("--questions", default=str(EVAL_DIR / "questions.json"))
    parser.add_argument("--render", help="다시 실행하지 않고 결과 json(검토 내용 포함)으로 md만 다시 만듭니다.")
    args = parser.parse_args()

    if args.render:
        path = Path(args.render)
        data = json.loads(path.read_text(encoding="utf-8"))
        if all("text" in d for r in data["results"] for d in r["top_k"]):
            capture_pages(data["results"], path.parent / "captures" / path.stem)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            print("검색 청크 본문(text)이 없는 결과라 캡처를 건너뜁니다.")
        path.with_suffix(".md").write_text(to_markdown(data, data["questions"], data["results"]), encoding="utf-8")
        print(f"기록: {path.with_suffix('.md')}")
        return

    global app
    import app as app_module
    app = app_module
    label = args.label or args.mode
    questions = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    if args.mode not in app.RETRIEVER_MODES:
        sys.exit(f"지원하지 않는 검색 방식: {args.mode} (가능: {', '.join(app.RETRIEVER_MODES)})")
    rows = run(args.mode, questions)

    out_dir = EVAL_DIR / "results"
    out_dir.mkdir(exist_ok=True)
    stem = f"{datetime.now():%Y%m%d_%H%M}_{label}"
    capture_pages(rows, out_dir / "captures" / stem)
    meta = {"mode": args.mode, "label": label, "description": app.RETRIEVER_MODES[args.mode],
            "run_at": f"{datetime.now():%Y-%m-%d %H:%M}", "top_k": app.TOP_K, "chunk_size": app.CHUNK_SIZE,
            "chunk_overlap": app.CHUNK_OVERLAP, "embedding_model": app.EMBEDDING_MODEL, "answer_model": app.MODEL_NAME}
    (out_dir / f"{stem}.json").write_text(json.dumps({**meta, "questions": questions, "results": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    report = to_markdown(meta, questions, rows)
    (out_dir / f"{stem}.md").write_text(report, encoding="utf-8")
    print(report.split("## 질문별 기록")[0])
    print(f"기록: {out_dir / stem}.md / .json")
    print("답변을 검토했다면 json의 각 결과에 \"verdict\"(O/△/X)와 \"review\"(문제점 목록)를 넣고 --render로 md를 다시 만드세요.")


if __name__ == "__main__":
    main()
