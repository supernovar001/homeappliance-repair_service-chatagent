# -*- coding: utf-8 -*-
"""상담 AI 연결. 레포 루트의 app.py(검색·상담 체인·안전 검사)를 지연 import해서 그대로 씁니다.

app.py를 모듈로 쪼개지 않는 이유: 평가 스크립트가 app.retriever를 바꿔 끼워 검색 방식을 비교합니다.
테스트는 OpenAI를 부르지 않는 FakeEngine을 씁니다.
"""
import os
import re
import struct
import time
import zlib
import threading
from functools import lru_cache


def _cpu_quota():
    """컨테이너(cgroup v2)에 걸린 CPU 한도. 호스트 코어 수와 다를 수 있습니다."""
    try:
        quota, period = open("/sys/fs/cgroup/cpu.max").read().split()
        return "제한 없음" if quota == "max" else f"{int(quota) / int(period):g}개"
    except (OSError, ValueError):
        return "-"


def _set_torch_threads():
    """TORCH_NUM_THREADS가 있으면 재정렬 모델의 CPU 스레드 수로 씁니다. 시작 로그에 CPU 수와 함께 남깁니다."""
    import torch
    threads = os.getenv("TORCH_NUM_THREADS", "").strip()
    if threads.isdigit() and int(threads) > 0:
        torch.set_num_threads(int(threads))
    print(f"CPU {os.cpu_count()}개(컨테이너 한도 {_cpu_quota()}), torch 스레드 {torch.get_num_threads()}개")


def _timed(rerank_scores):
    """재정렬 호출마다 쌍 수와 걸린 시간(잠금 대기 포함)을 남깁니다. 검색 구간 중 재정렬 몫을 따로 보려는 것입니다."""
    def timed(pairs):
        start = time.perf_counter()
        scores = rerank_scores(pairs)
        print(f"재정렬 {len(pairs)}쌍 {time.perf_counter() - start:.2f}초")
        return scores
    return timed


class WasherEngine:
    def __init__(self):
        self.ai = None
        self._lock = threading.Lock()

    @property
    def ready(self):
        return self.ai is not None

    def load(self):
        """app.py를 불러옵니다(PDF·Qdrant 색인·검색기). 재정렬 모델도 미리 불러 첫 질문이 기다리지 않게 합니다."""
        with self._lock:
            if self.ai is None:
                import app as ai
                if isinstance(ai.retriever, ai.ParentChildRetriever):
                    _set_torch_threads()
                    ai.reranker()
                    # 검색기는 호출할 때마다 모듈의 rerank_scores를 찾으므로, 바꿔 끼우면 서비스 호출만 시간을 잽니다(평가는 app.py를 직접 씀).
                    ai.rerank_scores = _timed(ai.rerank_scores)
                    # 첫 predict는 연산 준비로 느립니다. 시작할 때 한 번 돌려 첫 질문이 그 시간을 기다리지 않게 합니다.
                    ai.rerank_scores([("워밍업", "워밍업")])
                ai.demo.queue(default_concurrency_limit=1)  # /demo는 서비스 작업과 CPU를 나눠 쓰므로 한 번에 하나만
                self.ai = ai
        return self

    @property
    def demo(self):
        return self.ai.demo

    @property
    def demo_auth(self):
        return self.ai.AUTH

    def examples(self):
        return list(self.ai.EXAMPLE_QUESTIONS)

    def consult(self, question, history, memories, checklist, emit):
        return self.ai.consult_flow.invoke({"question": question, "history": history, "memories": memories,
                                            "checklist": checklist, "emit": emit})["result"]

    def evidence_pages(self, result):
        return self.ai.evidence_pages(result)

    def draft_memories(self, user_messages):
        return self.ai.draft_memories(user_messages)

    def page_png(self, page, highlights=()):
        """설명서 페이지 PNG. highlights(근거 문단)가 있으면 그 위치를 형광펜으로 칠합니다."""
        return _page_png(self.ai.PDF_PATH, page, tuple(highlights))


def _highlight_rects(page, text):
    """근거 문단이 페이지 어디에 있는지 찾아 사각형 목록을 돌려줍니다(src/capstone_eval.py와 같은 방식).
    PDF 추출 텍스트와 화면 배치가 달라 문단 전체를 한 번에 찾을 수 없으므로 3어절 창을 한 어절씩 밀며 찾고,
    여러 곳에서 나오는 흔한 문구는 한 곳에서만 나오는 문구들이 정한 세로 범위 안의 것만 씁니다."""
    words = text.split()
    windows = [" ".join(words[i:i + 3]) for i in range(max(1, len(words) - 2))]
    found = [page.search_for(w) for w in windows if len(w) >= 4]
    unique = [r[0] for r in found if len(r) == 1]
    if not unique:
        return [rect for rects in found for rect in rects]
    top, bottom = min(r.y0 for r in unique) - 15, max(r.y1 for r in unique) + 15
    return [rect for rects in found for rect in rects if top <= rect.y0 and rect.y1 <= bottom]


@lru_cache(maxsize=24)  # PNG 바이트(1쪽 약 0.3~0.6MB)만 캐시합니다.
def _page_png(pdf_path, page_no, highlights):
    import pymupdf
    with pymupdf.open(str(pdf_path)) as pdf:
        page = pdf[page_no - 1]
        for text in highlights:
            rects = _highlight_rects(page, text)
            if rects:
                page.add_highlight_annot(rects)
        return page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), annots=True).tobytes("png")


class FakeEngine:
    """테스트용 엔진. 질문에 'FAIL'이 있으면 실패하고, 'SLOW'가 있으면 release()까지 기다립니다."""
    demo = None
    demo_auth = None
    ready = True

    def __init__(self):
        self.calls = []
        self.gate = threading.Event()
        self.gate.set()

    def load(self):
        return self

    def examples(self):
        return ["OE가 떠요. 물이 안 빠져요.", "통살균은 얼마나 자주 하나요?"]

    def consult(self, question, history, memories, checklist, emit):
        self.calls.append({"question": question, "history": history, "memories": memories, "checklist": checklist})
        for stage in ("scope_check", "retrieving", "generating", "verifying"):
            emit(stage)
            if "SLOW" in question:
                self.gate.wait(10)
        if "FAIL" in question:
            raise RuntimeError("가짜 실패")
        reported = "그래도" in question
        return {
            "answer": "판단: 자가 점검 우선\n이유: 배수 문제입니다.\n\n배수 호스를 확인하세요 [PDF 41쪽].",
            "route": "자가 점검 우선", "decision_reason": "배수 문제입니다.", "scope": "워시타워 세탁기",
            "retrieved_pages": [41, 56], "contexts": [{"page": 41, "text": "배수 호스가 꺾이지 않았는지 확인하세요.", "code_priority": False}],
            "revision_failed": False, "safety_notes_added": [], "symptom": "OE 표시",
            "error_code": (re.findall(r"OE|UE|LE", question) or [None])[0],
            "checklist": [
                {"key": "drain_hose", "title": "배수 호스 꺾임·높이 확인", "detail": "꺾임을 펴 주세요.", "pages": [41], "kind": "self_check",
                 "customer_report": "확인 완료" if reported else "미확인", "customer_outcome": "해결되지 않음" if reported else "결과 불명",
                 "evidence": question if reported else "", "enabled": True},
                {"key": "pump_filter", "title": "배수 펌프 거름망 청소", "detail": "잔수 제거 후 청소", "pages": [56], "kind": "self_check",
                 "customer_report": "미확인", "customer_outcome": "결과 불명", "evidence": "", "enabled": True},
            ],
        }

    def evidence_pages(self, result):
        return [41], "답변에서 인용"

    def draft_memories(self, user_messages):
        text = "\n".join(user_messages)
        if "호스" not in text:
            return []
        return [{"symptom": "OE 표시", "action": "배수 호스를 바로 놓음", "outcome": "해결되지 않음", "evidence": user_messages[-1]}]

    def page_png(self, page, highlights=()):
        self.calls.append({"page": page, "highlights": list(highlights)})
        return _blank_png()


@lru_cache(maxsize=1)
def _blank_png(width=600, height=800):
    """화면 검사용 흰 페이지 PNG(가짜 엔진이 돌려줍니다)."""
    rows = b"".join(b"\x00" + b"\xff" * (width * 3) for _ in range(height))
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))
