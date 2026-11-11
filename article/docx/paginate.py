"""Page numbers for the Sumário and the lists of the Word report.

Uso, na raiz do repositório (precisa do LibreOffice e do PyMuPDF):

    uvx --with pymupdf python article/docx/paginate.py [--soffice PATH]

Builds article/main-article.docx, converts it to PDF with LibreOffice, finds the page of
every heading and caption, writes article/docx/pages.json and builds the document again
with those numbers. Repeats until the numbers stop changing (at most three rounds). Page
numbers count from the cover, as in the template, so they equal the PDF page index.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_docx  # noqa: E402

PAGES = Path(__file__).resolve().parent / "pages.json"


def norm(text: str) -> str:
    # Case is kept: "REFERÊNCIAS" must not match the word "referências" in the body.
    return re.sub(r"\s+", " ", text).strip()


def to_pdf(docx: Path, soffice: str, workdir: Path) -> Path:
    subprocess.run([soffice, "--headless", "--norestore",
                    f"-env:UserInstallation=file://{workdir}/profile",
                    "--convert-to", "pdf", "--outdir", str(workdir), str(docx)],
                   check=True, capture_output=True, timeout=300)
    return workdir / (docx.stem + ".pdf")


def locate(pdf: Path, doc: build_docx.Doc) -> dict:
    pages = [norm(p.get_text()) for p in pymupdf.open(pdf)]
    start = next(i for i, t in enumerate(pages) if "1 INTRODUÇÃO" in t and "SUMÁRIO" not in t)
    found = {"headings": {}, "captions": {}}
    for _, text, _ in doc.toc:
        key = norm(text)[:40]
        found["headings"][text] = next((i + 1 for i in range(start, len(pages))
                                        if key in pages[i]), None)
    for _, text in doc.captions:
        key = norm(text)[:40]
        found["captions"][text] = next((i + 1 for i in range(start, len(pages))
                                        if key in pages[i]), None)
    found["total_pages"] = len(pages)
    return found


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--soffice", default=shutil.which("soffice") or "soffice")
    args = ap.parse_args()
    pages = json.loads(PAGES.read_text()) if PAGES.exists() else {}
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        for _ in range(3):
            out = build_docx.assemble(pages)
            _, doc, _ = build_docx.build(pages)
            new = locate(to_pdf(out, args.soffice, work), doc)
            missing = [k for sec in ("headings", "captions")
                       for k, v in new[sec].items() if v is None]
            if missing:
                raise SystemExit(f"not found in the PDF: {missing}")
            if new == pages:
                break
            pages = new
            PAGES.write_text(json.dumps(pages, ensure_ascii=False, indent=1) + "\n")
        build_docx.assemble(pages)
    print(f"{pages['total_pages']} pages; {PAGES}")


if __name__ == "__main__":
    main()
