# -*- coding: utf-8 -*-
"""Baseline과 개선 Pipeline 비교 (14.7)

같은 질문 집합으로 실행한 두 결과 파일을 비교해 표를 만듭니다.
  python eval/compare.py eval/results/<baseline>.json eval/results/<개선>.json

판단 순서: 문서 근거 여부 → 정답 문서 포함 여부 → 그룹 재현율 → 첫 정답 순위
답변 변화의 '좋아짐/나빠짐'은 이 순서로 처음 달라지는 항목으로 정합니다.
"""
import json
import sys
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path


def cell(text):
    """표 칸 안에서 줄바꿈과 | 가 표를 깨지 않도록 바꿉니다."""
    return text.replace("|", "\\|").replace("\n\n", "<br>").replace("\n", "<br>")


def mark(value):
    return "-" if value is None else ("O" if value else "X")


def search_cell(r):
    hit = "-" if r["hit"] is None else ("O" if r["hit"] else "X")
    rank = f" {r['first_rank']}위" if r["first_rank"] else ""
    return f"포함 {hit}{rank} · {r['retrieved_pages']}"


def score(r):
    # 비교용 순서쌍: 클수록 좋음
    return (bool(r["grounded"]), bool(r["hit"]), r["group_recall"] or 0, -(r["first_rank"] or 99))


def reasons(a, b):
    notes = []
    if a["grounded"] != b["grounded"]:
        notes.append(f"문서 근거 {mark(a['grounded'])}→{mark(b['grounded'])}")
    if a["hit"] != b["hit"]:
        notes.append(f"정답 문서 포함 {mark(a['hit'])}→{mark(b['hit'])}")
    if a["group_recall"] != b["group_recall"] and a["group_recall"] is not None:
        notes.append(f"그룹 재현율 {a['group_recall']}→{b['group_recall']}")
    if a["first_rank"] != b["first_rank"]:
        notes.append(f"첫 정답 순위 {a['first_rank'] or '-'}→{b['first_rank'] or '-'}")
    if a["cited_pages"] != b["cited_pages"]:
        notes.append(f"인용 {a['cited_pages'] or '-'}→{b['cited_pages'] or '-'}")
    if a["route"] != b["route"]:
        notes.append(f"판단 '{a['route']}'→'{b['route']}'")
    fixed = sorted({p["detail"] for p in a["problems"]} - {p["detail"] for p in b["problems"]})
    new = sorted({p["detail"] for p in b["problems"]} - {p["detail"] for p in a["problems"]})
    notes += [f"해소: {d}" for d in fixed] + [f"새 문제: {d}" for d in new]
    return " / ".join(notes) or "검색·답변 지표 변화 없음"


def summary(rows):
    scored = [r for r in rows if r["hit"] is not None]
    hit = sum(bool(r["hit"]) for r in scored)
    grounded = sum(bool(r["grounded"]) for r in rows)
    mrr = sum(1 / r["first_rank"] if r["first_rank"] else 0 for r in scored) / max(1, len(scored))
    return hit, len(scored), grounded, len(rows), mrr


def main():
    if len(sys.argv) != 3:
        sys.exit("사용법: python eval/compare.py <baseline.json> <개선.json>")
    base, new = (json.loads(Path(p).read_text(encoding="utf-8")) for p in sys.argv[1:])
    if [q["question"] for q in base["questions"]] != [q["question"] for q in new["questions"]]:
        sys.exit("두 결과의 질문 집합이 다릅니다. 같은 questions.json으로 실행한 결과만 비교할 수 있습니다.")

    bh, bn, bg, bt, bm = summary(base["results"])
    nh, nn, ng, nt, nm = summary(new["results"])
    lines = [
        f"# Baseline과 개선 Pipeline 비교: {base['label']} vs {new['label']}", "",
        f"- Baseline: `{base['mode']}` — {base.get('description', '')}",
        f"- 개선: `{new['mode']}` — {new.get('description', '')}",
        f"- 작성 시각: {datetime.now():%Y-%m-%d %H:%M}", "",
        "## 요약", "",
        "| 지표 | Baseline | 개선 |", "|---|---|---|",
        f"| 정답 문서 포함 | {bh}/{bn} | {nh}/{nn} |",
        f"| MRR | {bm:.2f} | {nm:.2f} |",
        f"| 문서 근거 있는 답변 | {bg}/{bt} | {ng}/{nt} |", "",
        "## 질문별 비교", "",
        "| 질문 | Baseline 검색 | 개선 검색 | 답변 변화 | 판단 근거 |", "|---|---|---|---|---|",
    ]
    tally = {"좋아짐": 0, "동일": 0, "나빠짐": 0}
    for q, a, b in zip(base["questions"], base["results"], new["results"]):
        change = "좋아짐" if score(b) > score(a) else "나빠짐" if score(b) < score(a) else "동일"
        tally[change] += 1
        lines.append(f"| {q['id']} ({q['type']}) | {search_cell(a)} | {search_cell(b)} | {change} | {reasons(a, b)} |")
    lines += ["", f"좋아짐 {tally['좋아짐']} · 동일 {tally['동일']} · 나빠짐 {tally['나빠짐']}"]

    # 같은 질문에 대한 두 답변을 나란히 놓고 사람이 직접 판정하는 표
    lines += [
        "", "## 답변 비교 (수동 검토용)", "",
        "같은 질문에 대한 두 답변을 나란히 놓았습니다. '자동 판정'은 위 표의 지표 기준이며, 답변 내용까지는 보지 않습니다.",
        "'검토' 칸에 직접 **동일 / 좋아짐 / 나빠짐**을 적어 주세요. '텍스트'는 두 답변 문장이 얼마나 같은지(difflib 유사도)입니다.",
        "'검색 결과'가 같은데 답변이 다르면, 그 차이는 검색이 아니라 답변 모델의 실행마다의 변동입니다(개선 효과로 보면 안 됨).", "",
        f"| 질문 | {base['label']} 답변 | {new['label']} 답변 | 검색 결과 | 텍스트 | 자동 판정 | 검토 |", "|---|---|---|---|---|---|---|",
    ]
    for q, a, b in zip(base["questions"], base["results"], new["results"]):
        change = "좋아짐" if score(b) > score(a) else "나빠짐" if score(b) < score(a) else "동일"
        ratio = SequenceMatcher(None, a["answer"], b["answer"]).ratio()
        text = "완전히 같음" if a["answer"] == b["answer"] else f"다름 (유사도 {ratio:.0%})"
        question = f"**{q['id']}** {q['type']}<br>{cell(q['question'])}"
        answer_a = f"{cell(a['answer'])}<br>_인용: {a['cited_pages'] or '-'}_"
        answer_b = f"{cell(b['answer'])}<br>_인용: {b['cited_pages'] or '-'}_"
        ids_a, ids_b = [d["chunk_id"] for d in a["top_k"]], [d["chunk_id"] for d in b["top_k"]]
        search = "같음" if ids_a == ids_b else ("같은 청크, 순서만 다름" if sorted(ids_a) == sorted(ids_b) else "다름")
        lines.append(f"| {question} | {answer_a} | {answer_b} | {search} | {text} | {change} | |")

    out = Path(sys.argv[2]).with_name(f"compare_{base['label']}_vs_{new['label']}.md")
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"\n기록: {out}")


if __name__ == "__main__":
    main()
