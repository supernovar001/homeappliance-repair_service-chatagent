# -*- coding: utf-8 -*-
"""Baseline과 개선 Pipeline 비교 (14.7)

같은 질문 집합으로 실행한 결과 파일 2개 이상을 순서대로 비교해 표를 만듭니다.
  python eval/compare.py <baseline.json> <개선.json>
  python eval/compare.py <baseline.json> <current.json> <improved.json>
  python eval/compare.py <baseline.json> <improved.json> --notes eval/changes/baseline_to_improved.md
  (--notes: 변경 이력 등 사람이 쓴 md를 비교 문서 앞부분에 넣습니다)

파일을 넘긴 순서가 개선 단계 순서입니다. 인접한 두 단계(예: baseline→current, current→improved)와
처음→마지막(baseline→improved)의 변화를 함께 기록합니다.

자동 판정 순서: 문서 근거 여부 → 정답 문서 포함 여부 → 그룹 재현율 → 첫 정답 순위
답변 내용은 보지 않으므로, 답변 비교 표의 '검토' 칸에 사람이 직접 판정합니다.
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
    return f"포함 {hit}{rank}<br>{r['retrieved_pages']}"


def score(r):
    # 비교용 순서쌍: 클수록 좋음
    return (bool(r["grounded"]), bool(r["hit"]), r["group_recall"] or 0, -(r["first_rank"] or 99))


def change(a, b):
    return "좋아짐" if score(b) > score(a) else "나빠짐" if score(b) < score(a) else "동일"


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
    return "<br>".join(cell(n) for n in notes) or "변화 없음"


def same_search(a, b):
    ids_a, ids_b = [d["chunk_id"] for d in a["top_k"]], [d["chunk_id"] for d in b["top_k"]]
    return "같음" if ids_a == ids_b else ("순서만 다름" if sorted(ids_a) == sorted(ids_b) else "다름")


def text_similarity(a, b):
    if a["answer"] == b["answer"]:
        return "완전히 같음"
    return f"{SequenceMatcher(None, a['answer'], b['answer']).ratio():.0%}"


def summary(rows):
    scored = [r for r in rows if r["hit"] is not None]
    mrr = sum(1 / r["first_rank"] if r["first_rank"] else 0 for r in scored) / max(1, len(scored))
    verdicts = [r.get("verdict") for r in rows if r.get("verdict")]
    return {
        "hit": f"{sum(bool(r['hit']) for r in scored)}/{len(scored)}",
        "mrr": f"{mrr:.2f}",
        "grounded": f"{sum(bool(r['grounded']) for r in rows)}/{len(rows)}",
        "review": (f"O {verdicts.count('O')} · △ {verdicts.count('△')} · X {verdicts.count('X')}" if len(verdicts) == len(rows) else "미검토"),
    }


def main():
    args = sys.argv[1:]
    notes = None
    if "--notes" in args:
        i = args.index("--notes")
        notes = Path(args[i + 1]).read_text(encoding="utf-8").strip()
        args = args[:i] + args[i + 2:]
    paths = args
    if len(paths) < 2:
        sys.exit("사용법: python eval/compare.py <baseline.json> <개선.json> [<개선2.json> ...]")
    runs = [json.loads(Path(p).read_text(encoding="utf-8")) for p in paths]
    questions = runs[0]["questions"]
    if any([q["question"] for q in r["questions"]] != [q["question"] for q in questions] for r in runs[1:]):
        sys.exit("결과들의 질문 집합이 다릅니다. 같은 questions.json으로 실행한 결과만 비교할 수 있습니다.")

    labels = [r["label"] for r in runs]
    steps = [(i, i + 1) for i in range(len(runs) - 1)]
    if len(runs) > 2:
        steps.append((0, len(runs) - 1))  # 처음→마지막(전체 개선 효과)
    step_name = lambda s: f"{labels[s[0]]}→{labels[s[1]]}"

    lines = [f"# Baseline과 개선 Pipeline 비교: {' vs '.join(labels)}", ""]
    lines += [f"- `{r['label']}` — {r.get('description', '')}" for r in runs]
    lines += [f"- 작성 시각: {datetime.now():%Y-%m-%d %H:%M}", ""]
    if notes:
        lines += [notes, "", "---", "", "아래는 결과 파일에서 자동으로 만든 비교입니다.", ""]

    sums = [summary(r["results"]) for r in runs]
    lines += ["## 자동 비교 요약", "", "| 지표 | " + " | ".join(labels) + " |", "|---|" + "---|" * len(runs)]
    for key, name in [("hit", "정답 문서 포함"), ("mrr", "MRR"), ("grounded", "문서 근거 있는 답변(자동)"), ("review", "답변 수동 검토")]:
        lines.append(f"| {name} | " + " | ".join(s[key] for s in sums) + " |")

    lines += ["", "## 단계별 변화 (자동 판정)", "", "| 단계 | 좋아짐 | 동일 | 나빠짐 | 좋아진 질문 | 나빠진 질문 |", "|---|---|---|---|---|---|"]
    for s in steps:
        res = [change(runs[s[0]]["results"][i], runs[s[1]]["results"][i]) for i in range(len(questions))]
        up = [q["id"] for q, c in zip(questions, res) if c == "좋아짐"]
        down = [q["id"] for q, c in zip(questions, res) if c == "나빠짐"]
        lines.append(f"| {step_name(s)} | {res.count('좋아짐')} | {res.count('동일')} | {res.count('나빠짐')} | {', '.join(up) or '-'} | {', '.join(down) or '-'} |")

    lines += ["", "## 질문별 검색·지표 비교", "",
              "| 질문 | " + " | ".join(f"{l} 검색" for l in labels) + " | " + " | ".join(step_name(s) for s in steps) + " |",
              "|---|" + "---|" * (len(runs) + len(steps))]
    for i, q in enumerate(questions):
        searches = [search_cell(r["results"][i]) for r in runs]
        deltas = []
        for s in steps:
            a, b = runs[s[0]]["results"][i], runs[s[1]]["results"][i]
            deltas.append(f"**{change(a, b)}**<br>{reasons(a, b)}")
        lines.append(f"| {q['id']} ({q['type']}) | " + " | ".join(searches + deltas) + " |")

    lines += [
        "", "## 답변 비교 (수동 검토용)", "",
        "같은 질문에 대한 답변을 단계별로 나란히 놓았습니다. '자동'은 위 지표 기준이며 답변 내용은 보지 않습니다.",
        "'검색'이 같은데 답변이 다르면 그 차이는 검색이 아니라 답변 생성(프롬프트 변경 또는 실행마다의 변동) 때문입니다.",
        "'검토' 칸에 직접 **동일 / 좋아짐 / 나빠짐**을 적어 주세요. 답변 아래 _검토: O/△/X_ 는 각 결과 기록에 남긴 수동 판정입니다.", "",
        "| 질문 | " + " | ".join(f"{l} 답변" for l in labels) + " | " + " | ".join(f"{step_name(s)}<br>(검색 · 텍스트 · 자동)" for s in steps)
        + " | " + " | ".join(f"검토<br>{step_name(s)}" for s in steps) + " |",
        "|---|" + "---|" * (len(runs) + 2 * len(steps)),
    ]
    for i, q in enumerate(questions):
        answers = []
        for r in runs:
            row = r["results"][i]
            verdict = f" · _검토: {row['verdict']}_" if row.get("verdict") else ""
            answers.append(f"{cell(row['answer'])}<br>_인용: {row['cited_pages'] or '-'}_{verdict}")
        deltas = []
        for s in steps:
            a, b = runs[s[0]]["results"][i], runs[s[1]]["results"][i]
            deltas.append(f"검색 {same_search(a, b)}<br>텍스트 {text_similarity(a, b)}<br>자동 {change(a, b)}")
        lines.append(f"| **{q['id']}** {q['type']}<br>{cell(q['question'])} | " + " | ".join(answers + deltas) + " |" + " |" * len(steps))

    out = Path(paths[-1]).with_name(f"compare_{'_vs_'.join(labels)}.md")
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[: lines.index("## 질문별 검색·지표 비교")]))
    print(f"기록: {out}")


if __name__ == "__main__":
    main()
