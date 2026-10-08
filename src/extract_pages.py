# -*- coding: utf-8 -*-
"""매뉴얼 PDF를 페이지별 Markdown으로 추출합니다. 추출 결과를 직접 검수·수정하면 app.py가 그 파일을 색인합니다.

사용법 (practice 폴더에서)
  python3 src/extract_pages.py                       # 세탁기 검색 대상 페이지 추출, 이미 있는 파일은 건너뜀
  python3 src/extract_pages.py --pages 55 56 --force # 지정 페이지만 다시 추출(기존 파일은 .md.bak으로 보관)

결과
  data/pages/p055.md          검수·수정할 텍스트 (app.py 색인 대상)
  data/page_images/p055.png   대조용 원본 페이지 이미지

추출 규칙
  - 쪽 번호·머리글(페이지 상단 40pt)은 본문에서 빼고 첫 줄 주석의 '머리글'로 남깁니다.
  - 2단 페이지는 전체 폭 블록을 경계로 왼쪽 단 → 오른쪽 단 순서로 읽습니다.
  - 표는 PyMuPDF find_tables()로 찾아 마크다운 표로 넣습니다(병합 셀은 같은 값으로 채워집니다).
  - 15pt 이상 굵은 글씨는 '#', 11pt 이상 굵은 글씨는 '##' 제목으로 둡니다. app.py는 이 제목 단위로 parent 청크를 만듭니다.
"""
import argparse
import re
import shutil
import unicodedata
from pathlib import Path
import pymupdf

ROOT = Path(__file__).resolve().parent.parent
PDF_PATH = ROOT / "wachingmachine_service_manual.pdf"
PAGES_DIR = ROOT / "data" / "pages"
IMAGES_DIR = ROOT / "data" / "page_images"
# app.py 기존 색인(legacy_index)의 세탁기 검색 대상 페이지와 같습니다.
WASHER_PAGES = list(range(3, 10)) + list(range(14, 28)) + list(range(39, 44)) + list(range(47, 60)) + [64]

HEADER_BOTTOM = 40   # 이 y좌표보다 위는 쪽 번호·머리글 영역입니다.
TITLE_SIZE = 14.0    # 15.1pt 굵게(예: '세탁기') → '#'
HEADING_SIZE = 11.0  # 11.2pt 굵게(예: '급수구 거름망 청소하기') → '##'. 본문은 8.8pt입니다.
LABEL_SIZE = 9.5     # 9.7pt 굵게(예: '알아두기') → **굵게**
STEP_SIZE = 13.0     # 13.2pt 굵은 숫자는 절차 번호입니다.
BULLET = re.compile(r"[•\-–·※]|\d+\.\s|\*\*|\|")

README = """# 페이지 Markdown 검수 안내

`python3 src/extract_pages.py`가 만든 파일입니다. `../page_images/`의 원본 이미지와 나란히 보며 고치세요.

- 첫 줄 주석의 `검수: 미완료`를 고친 뒤 `검수: 완료`로 바꾸세요. app.py가 시작할 때 미완료 페이지를 알려줍니다.
- `#`, `##` 제목이 parent 청크의 경계입니다. 제목이 빠졌거나 잘못 붙었으면 바로잡으세요(`###` 이하는 본문으로 취급).
- 표는 `| 열 | 열 |` 마크다운 표로 두세요. 한 행이 child 청크 하나가 되고, 첫 열이 같은 행들은 한 parent로 묶입니다.
- 문단은 빈 줄로 구분합니다. 2단 페이지의 읽기 순서가 섞였으면 문단 순서를 옮기세요.
- 파일을 고치면 app.py가 다음 실행 때 내용 변화를 감지해 Qdrant 색인을 다시 만듭니다.
"""


def clean(text):
    # 17쪽처럼 추출이 깨진 페이지에는 단독 서로게이트가 섞여 있습니다(API 요청 시 UnicodeEncodeError).
    text = re.sub(r"[\ud800-\udfff]", "", unicodedata.normalize("NFC", text or ""))
    return re.sub(r"[ \t ]+", " ", text).strip()


def is_bold(span):
    return bool(span["flags"] & 16) or "Bold" in span["font"]


def inside(bbox, area):
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    return area[0] <= cx <= area[2] and area[1] <= cy <= area[3]


def block_lines(block):
    """텍스트 블록의 줄을 (글자, 크기, 굵게 여부)로 돌려줍니다."""
    lines = []
    for line in block["lines"]:
        spans = [s for s in line["spans"] if s["text"].strip()]
        if spans:
            text = "".join(lcd_text(s) for s in line["spans"])
            lines.append((clean(text), max(s["size"] for s in spans), all(is_bold(s) for s in spans)))
    return lines


LCD_FIXES = {"1E": "IE", "[L": "CL"}  # 표시창 글꼴에서 다른 글자로 추출되는 코드(원본 이미지로 확인)

def lcd_text(span):
    # 표시창 글꼴(LG_LCD)은 텍스트로 뽑으면 글자가 바뀝니다: 2 → 'z'(dE2 → 'dEz'), 40쪽 IE → '1E', 56쪽 CL → '[L'.
    if "LCD" not in span["font"]:
        return span["text"]
    text = span["text"].replace("z", "2")
    return LCD_FIXES.get(text.strip(), text)


def render_lines(lines):
    """줄을 Markdown으로 바꿉니다. 글머리표가 아닌 줄은 앞 줄에 이어 붙여 줄바꿈된 문장을 복원합니다.
    None은 문단 경계입니다."""
    out, step = [], None
    for item in lines:
        if item is None:
            out.append("")
            continue
        text, size, bold = item
        if text.isdigit() and size >= STEP_SIZE:
            out.append("")
            step = text
            continue
        if bold and size >= HEADING_SIZE:
            out += ["", f"{'#' if size >= TITLE_SIZE else '##'} {text}", ""]
            continue
        if bold and size >= LABEL_SIZE:
            out += ["", f"**{text}**"]
            continue
        if step:
            text, step = f"{step}. {text}", None
            out.append(text)
        elif out and out[-1] and not out[-1].startswith(("#", "**")) and not BULLET.match(text):
            out[-1] += " " + text
        else:
            out.append(text)
    return out


def extract_page(page):
    """한 페이지를 (머리글, Markdown 본문)으로 추출합니다."""
    mid = page.rect.width / 2
    # '알아두기' 상자처럼 테두리만 있는 영역도 표로 잡히므로, 값이 2칸 이상 찬 행이 2개 이상인 것만 표로 봅니다.
    tables = [t for t in page.find_tables().tables
              if sum(sum(bool((c or "").strip()) for c in row) >= 2 for row in t.extract()) >= 2]
    header, elements = [], []
    for block in page.get_text("dict")["blocks"]:
        if block["type"] != 0:
            continue
        lines = block_lines(block)
        if not lines:
            continue
        if block["bbox"][3] <= HEADER_BOTTOM:
            header += [t for t, _, _ in lines if not t.isdigit()]
        elif not any(inside(block["bbox"], t.bbox) for t in tables):
            elements.append({"bbox": block["bbox"], "lines": lines})
    for table in tables:
        # 표 셀은 글꼴 정보 없이 나오므로 오류코드 모양만 골라 고칩니다: dEz·LEz·tEz → 2, 셀 전체가 '[L'이면 CL.
        markdown = re.sub(r"(?<=[dLt]E)z(?![A-Za-z])", "2", table.to_markdown())
        markdown = re.sub(r"(?<=\|)\[L(?=\|)", "CL", markdown)
        elements.append({"bbox": table.bbox, "table": clean(markdown).replace("\n\n", "\n")})

    # 단 구분: 가운데선을 넘지 않으면 왼쪽(L)·오른쪽(R), 걸치면 전체 폭(F)입니다.
    for e in elements:
        x0, _, x1, _ = e["bbox"]
        e["col"] = "L" if x1 <= mid + 10 else "R" if x0 >= mid - 10 else "F"
    ordered, band = [], []
    for e in sorted(elements, key=lambda e: e["bbox"][1]):
        if e["col"] == "F":
            ordered += sorted(band, key=lambda e: (e["col"], e["bbox"][1])) + [e]
            band = []
        else:
            band.append(e)
    ordered += sorted(band, key=lambda e: (e["col"], e["bbox"][1]))

    # PDF는 한 줄을 블록 하나로 두는 경우가 많습니다. 같은 단에서 바로 아래(간격 4pt 미만)에 붙은 블록은
    # 같은 문단으로 이어 읽고, 그 밖에는 문단을 나눕니다. 절차 번호 다음 줄은 번호 글자가 커서 간격이
    # 7pt쯤 벌어지므로, 앞 블록보다 들여쓴 블록은 8pt 미만까지 이어 읽습니다.
    out, stream, prev = [], [], None
    for e in ordered:
        if "table" in e:
            out += render_lines(stream) + ["", e["table"], ""]
            stream, prev = [], None
            continue
        gap = e["bbox"][1] - prev["bbox"][3] if prev else None
        indented = prev and e["bbox"][0] > prev["bbox"][0] + 5
        if not (prev and prev["col"] == e["col"] and -2 <= gap < (8 if indented else 4)):
            stream.append(None)
        stream += e["lines"]
        prev = e
    out += render_lines(stream)
    body = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()
    return " ".join(dict.fromkeys(header)), body


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", type=int, nargs="+", help="추출할 페이지(기본: 세탁기 검색 대상 페이지)")
    parser.add_argument("--force", action="store_true", help="이미 있는 파일도 다시 추출(기존 파일은 .md.bak으로 보관)")
    args = parser.parse_args()

    PAGES_DIR.mkdir(parents=True, exist_ok=True)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    if not (PAGES_DIR / "README.md").exists():
        (PAGES_DIR / "README.md").write_text(README, encoding="utf-8")

    written, skipped = [], []
    with pymupdf.open(str(PDF_PATH)) as pdf:
        for number in args.pages or WASHER_PAGES:
            md_path = PAGES_DIR / f"p{number:03d}.md"
            if md_path.exists() and not args.force:
                skipped.append(number)
                continue
            if md_path.exists():
                shutil.copy(md_path, md_path.with_suffix(".md.bak"))
            page = pdf[number - 1]
            header, body = extract_page(page)
            md_path.write_text(
                f"<!-- page: {number} | 머리글: {header} | 검수: 미완료 -->\n"
                f"<!-- 원본: ../page_images/p{number:03d}.png -->\n\n{body or '(추출된 텍스트 없음)'}\n",
                encoding="utf-8",
            )
            page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5)).save(str(IMAGES_DIR / f"p{number:03d}.png"))
            written.append(number)

    print(f"추출 {len(written)}쪽 → {PAGES_DIR.relative_to(ROOT)}/  (원본 이미지: {IMAGES_DIR.relative_to(ROOT)}/)")
    if skipped:
        print(f"이미 있어서 건너뜀 {len(skipped)}쪽: {skipped}  (다시 추출하려면 --pages … --force)")


if __name__ == "__main__":
    main()
