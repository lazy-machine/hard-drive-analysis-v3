# ruff: noqa: E501  (long lines are WordprocessingML string literals)
"""Build the Word version of the technical report from main-article.md.

Uso, na raiz do repositório:

    python3 article/docx/build_docx.py [--pages article/docx/pages.json]

The output, article/main-article.docx, is the FATEC template (article/template/) with its
body replaced: the template keeps its styles, header logos, page size, margins and the
section break that starts page numbering at the Introdução. The Sumário and the lists of
illustrations and tables are generated from the headings and captions. Their page numbers
come from --pages, which paginate.py writes after rendering the document once; without it
they are left blank.

Only the Markdown that main-article.md uses is supported: # and ## headings, paragraphs,
"a)" list items, pipe tables, images, **bold**, *italic*, `code`, captions in bold
("**Tabela 1 – ...**") and "Fonte:" lines. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from xml.sax.saxutils import escape

ARTICLE = Path(__file__).resolve().parents[1]
TEMPLATE = ARTICLE / "template" / "Modelo de Relatório Técnico CD 2026.docx"
SOURCE = ARTICLE / "main-article.md"
OUTPUT = ARTICLE / "main-article.docx"

TEXT_WIDTH = 9071                      # A4 minus 3 cm + 2 cm margins, in twentieths of a point
EMU_PER_TWIP = 635
PRETEXT = {"RESUMO", "LISTA DE ILUSTRAÇÕES", "LISTA DE TABELAS",
           "LISTA DE ABREVIATURAS E SIGLAS", "SUMÁRIO"}
CAPTION = re.compile(r"^\*\*(Figura|Quadro|Tabela) (\d+) – (.+)\*\*$")
LIST_ITEM = re.compile(r"^[a-z]\) ")

# The template's Normal style is bold, so every plain run switches bold off.
BASE_RPR = '<w:rFonts w:cs="Arial"/>{b}{i}{font}<w:sz w:val="{sz}"/><w:szCs w:val="{sz}"/>'


COVER_GAP = 5200         # twips between the author line and the city, on the cover
KEEP_WHOLE = 8           # tables up to this many rows are not split across pages


def rpr(bold=False, italic=False, size=24, mono=False, caps=False, sup=False) -> str:
    font = '<w:rFonts w:ascii="Courier New" w:hAnsi="Courier New" w:cs="Courier New"/>' if mono else ""
    out = BASE_RPR.format(b="<w:b/>" if bold else '<w:b w:val="0"/>',
                          i="<w:i/>" if italic else "", font=font, sz=size)
    if mono:
        out = out.replace('<w:rFonts w:cs="Arial"/>', "", 1)
    out += '<w:caps/>' if caps else ""
    out += '<w:vertAlign w:val="superscript"/>' if sup else ""
    return f"<w:rPr>{out}</w:rPr>"


def run(text: str, **kw) -> str:
    return f'<w:r>{rpr(**kw)}<w:t xml:space="preserve">{escape(text)}</w:t></w:r>'


def inline(text: str, size=24, bold=False, italic=False) -> str:
    """Runs for a line of Markdown with **bold**, *italic*, `code` and exponents such as
    "^0,5", which become superscript."""
    out = []
    for tok in re.split(r"(`[^`]*`|\*\*|\*|\^\d+(?:,\d+)?)", text):
        if tok.startswith("^"):
            out.append(run(tok[1:], bold=bold, italic=italic, size=size, sup=True))
        elif tok == "**":
            bold = not bold
        elif tok == "*":
            italic = not italic
        elif tok.startswith("`") and tok.endswith("`") and len(tok) >= 2:
            out.append(run(tok[1:-1], bold=bold, italic=italic, size=size - 2, mono=True))
        elif tok:
            out.append(run(tok, bold=bold, italic=italic, size=size))
    return "".join(out)


def para(runs: str, *, jc="both", first=709, left=0, hanging=0, before=0, after=120,
         keep_next=False, keep_lines=False, page_break=False, style=None, tabs="",
         extra="") -> str:
    ind = (f'<w:ind w:left="{left}" w:hanging="{hanging}"/>' if hanging
           else f'<w:ind w:left="{left}" w:firstLine="{first}"/>')
    ppr = (f'<w:pStyle w:val="{style}"/>' if style else "") + \
          ('<w:keepNext/>' if keep_next else "") + \
          ('<w:keepLines/>' if keep_lines else "") + \
          ('<w:pageBreakBefore/>' if page_break else "") + tabs + \
          f'<w:spacing w:before="{before}" w:after="{after}" w:line="240" w:lineRule="auto"/>' + \
          ind + f'<w:jc w:val="{jc}"/>' + extra
    return f"<w:p><w:pPr>{ppr}</w:pPr>{runs}</w:p>"


def plain(md: str) -> str:
    """Markdown inline text without its markers."""
    return re.sub(r"\*\*|\*|`|\^(?=\d)", "", md)


class Doc:
    def __init__(self, pages: dict):
        self.pages = pages
        self.body: list[str] = []
        self.toc: list[tuple[int, str, str]] = []        # (level, text, bookmark)
        self.toc_md: dict[str, str] = {}                 # heading text -> its Markdown
        self.captions: list[tuple[str, str]] = []        # (kind, "Tabela 1 – ...")
        self.images: list[tuple[str, Path]] = []         # (rId, png)
        self.links: list[tuple[str, str]] = []           # (rId, target)
        self.bookmark = 0

    # -- pieces ------------------------------------------------------------------------

    def heading(self, level: int, md: str, center=False) -> str:
        text = plain(md)
        self.bookmark += 1
        name = f"_Toc{9000 + self.bookmark}"
        self.toc.append((level, text, name))
        self.toc_md[text] = md
        style = "Ttulo1" if level == 1 else "Ttulo2"
        runs = inline(md, bold=level == 1)
        return (f'<w:p><w:pPr><w:pStyle w:val="{style}"/>'
                + ('<w:pageBreakBefore/>' if level == 1 else "")
                + f'<w:spacing w:before="{0 if level == 1 else 240}" w:after="240"/>'
                + ('<w:jc w:val="center"/>' if center else "")
                + f'</w:pPr><w:bookmarkStart w:id="{self.bookmark}" w:name="{name}"/>{runs}'
                f'<w:bookmarkEnd w:id="{self.bookmark}"/></w:p>')

    def pretext_title(self, text: str) -> str:
        return para(run(text, bold=True), jc="center", first=0, after=480, page_break=True)

    def image(self, path: Path) -> str:
        png = path.with_suffix(".png")
        w, h = struct.unpack(">II", png.read_bytes()[16:24])
        cx = TEXT_WIDTH * EMU_PER_TWIP
        cy = round(cx * h / w)
        rid = f"rIdImg{len(self.images) + 1}"
        self.images.append((rid, png))
        n = len(self.images)
        drawing = (
            f'<w:r><w:rPr><w:noProof/></w:rPr><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0">'
            f'<wp:extent cx="{cx}" cy="{cy}"/><wp:docPr id="{100 + n}" name="Figura {n}"/>'
            '<wp:cNvGraphicFramePr><a:graphicFrameLocks xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" noChangeAspect="1"/></wp:cNvGraphicFramePr>'
            '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            f'<pic:nvPicPr><pic:cNvPr id="{100 + n}" name="{png.name}"/><pic:cNvPicPr/></pic:nvPicPr>'
            f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>'
            '</a:graphicData></a:graphic></wp:inline></w:drawing></w:r>')
        return para(drawing, jc="center", first=0, after=60, keep_next=True)

    def table(self, rows: list[list[str]], kind: str) -> str:
        """A pipe table. Tabela: open sides, rules above, below and under the header
        (IBGE style, as ABNT asks); Quadro: a closed grid."""
        ncol = len(rows[0])
        size = 18 if ncol >= 6 else 20          # 9 pt in the widest tables, 10 pt otherwise
        widths = column_widths(rows, ncol, size)
        line = '<w:{0} w:val="single" w:sz="6" w:space="0" w:color="000000"/>'
        if kind == "Quadro":
            borders = "".join(line.format(b) for b in ("top", "left", "bottom", "right",
                                                       "insideH", "insideV"))
        else:
            borders = line.format("top") + line.format("bottom")
        out = [f'<w:tbl><w:tblPr><w:tblW w:w="{TEXT_WIDTH}" w:type="dxa"/><w:jc w:val="center"/>'
               f'<w:tblBorders>{borders}</w:tblBorders><w:tblLayout w:type="fixed"/>'
               '<w:tblCellMar><w:left w:w="70" w:type="dxa"/><w:right w:w="70" w:type="dxa"/></w:tblCellMar>'
               '</w:tblPr><w:tblGrid>' + "".join(f'<w:gridCol w:w="{w}"/>' for w in widths)
               + "</w:tblGrid>"]
        whole = len(rows) <= KEEP_WHOLE
        for i, r in enumerate(rows):
            head = i == 0
            keep = whole or i < 3 or i >= len(rows) - 3   # no lone rows at either end
            trpr = "<w:trPr><w:tblHeader/><w:cantSplit/></w:trPr>" if head else "<w:trPr><w:cantSplit/></w:trPr>"
            cells = []
            for c in range(ncol):
                txt = r[c] if c < len(r) else ""
                bottom = line.format("bottom") if head and kind != "Quadro" else ""
                tcpr = (f'<w:tcPr><w:tcW w:w="{widths[c]}" w:type="dxa"/>'
                        + (f"<w:tcBorders>{bottom}</w:tcBorders>" if bottom else "")
                        + '<w:vAlign w:val="center"/></w:tcPr>')
                numeric = bool(re.fullmatch(r"[\s\d.,%+−\-\[\];×/]+", plain(txt))) and c > 0
                cells.append(f"<w:tc>{tcpr}" + para(inline(txt, size=size, bold=head),
                                                     jc="center" if head or numeric else "left",
                                                     first=0, after=0, before=0,
                                                     keep_next=keep) + "</w:tc>")
            out.append(f"<w:tr>{trpr}{''.join(cells)}</w:tr>")
        out.append("</w:tbl>")
        return "".join(out)

    # -- generated pre-text ---------------------------------------------------------------

    def _dotted(self, label_runs: str, page, level_first=0, left=0, hanging=0) -> str:
        tab = '<w:tabs><w:tab w:val="right" w:leader="dot" w:pos="9061"/></w:tabs>'
        num = run(str(page) if page else "", size=24)
        return para(label_runs + f"<w:r>{rpr()}<w:tab/></w:r>" + num, jc="left", first=level_first,
                    left=left, hanging=hanging, after=60, tabs=tab)

    def list_of(self, kinds: tuple[str, ...]) -> str:
        out = []
        for kind, text in self.captions:
            if kind in kinds:
                out.append(self._dotted(run(text), self.pages.get("captions", {}).get(text),
                                        left=0, hanging=0))
        return "".join(out)

    def summary(self) -> str:
        out = [f'<w:p><w:pPr><w:pStyle w:val="Sumrio1"/></w:pPr><w:r>{rpr()}<w:fldChar w:fldCharType="begin"/></w:r>'
               f'<w:r>{rpr()}<w:instrText xml:space="preserve"> TOC \\o "1-2" \\h \\z \\u </w:instrText></w:r>'
               f'<w:r>{rpr()}<w:fldChar w:fldCharType="separate"/></w:r></w:p>']
        for level, text, name in self.toc:
            page = self.pages.get("headings", {}).get(text, "")
            style = "Sumrio1" if level == 1 else "Sumrio2"
            pagefld = (f'<w:r>{rpr(bold=level == 1)}<w:fldChar w:fldCharType="begin"/></w:r>'
                       f'<w:r>{rpr(bold=level == 1)}<w:instrText xml:space="preserve"> PAGEREF {name} \\h </w:instrText></w:r>'
                       f'<w:r>{rpr(bold=level == 1)}<w:fldChar w:fldCharType="separate"/></w:r>'
                       + run(str(page), bold=level == 1)
                       + f'<w:r>{rpr(bold=level == 1)}<w:fldChar w:fldCharType="end"/></w:r>')
            label = inline(self.toc_md.get(text, text), bold=level == 1)
            out.append(f'<w:p><w:pPr><w:pStyle w:val="{style}"/><w:spacing w:after="60"/>'
                       '<w:jc w:val="left"/></w:pPr>'
                       f'<w:hyperlink w:anchor="{name}" w:history="1">{label}'
                       f'<w:r>{rpr(bold=level == 1)}<w:tab/></w:r>{pagefld}</w:hyperlink></w:p>')
        out.append(f'<w:p><w:pPr><w:pStyle w:val="Sumrio1"/></w:pPr><w:r>{rpr()}<w:fldChar w:fldCharType="end"/></w:r></w:p>')
        return "".join(out)


def column_widths(rows: list[list[str]], ncol: int, size: int = 20, pad: int = 200) -> list[int]:
    """Column widths in twips: each column fits its longest word (no word is broken) and
    keeps a bracketed interval such as "[0,895; 0,914]" on one line when it can; the
    rest of the text width goes to the columns with the most text."""
    def cells(c):
        return [plain(r[c]) if c < len(r) else "" for r in rows]

    def unit(text):   # pieces that should not wrap: words and whole intervals
        return re.findall(r"\[[^\]]*\]|\S+", text)

    def longest(texts):
        return max((len(u) for t in texts for u in unit(t)), default=0)

    # header cells are bold and often capitalized, so their letters are wider
    # Arial digits are 0.556 em wide; bold capitals in headers about 0.68 em (in twips)
    char, head = 0.556 * size * 10, 0.68 * size * 10
    minw = [max(longest(cells(c)[:1]) * head, longest(cells(c)[1:]) * char) + pad
            for c in range(ncol)]
    body = [max((len(t) for t in cells(c)[1:]), default=0) for c in range(ncol)]
    pref = [max(minw[c], min(body[c], 45) * char + pad) for c in range(ncol)]
    if sum(minw) >= TEXT_WIDTH:
        # Too wide: take the width back from the columns whose header is wider than their
        # cells, so that no number in the body is broken; only then shrink every column.
        floor = [min(minw[c], longest(cells(c)[1:]) * char + pad) for c in range(ncol)]
        slack = [m - f for m, f in zip(minw, floor, strict=True)]
        over = sum(minw) - TEXT_WIDTH
        if sum(slack) >= over > 0:
            widths = [m - over * k / sum(slack) for m, k in zip(minw, slack, strict=True)]
        else:
            widths = [m * TEXT_WIDTH / sum(minw) for m in minw]
    elif sum(pref) <= TEXT_WIDTH:
        widths = [p * TEXT_WIDTH / sum(pref) for p in pref]
    else:
        spare, extra = TEXT_WIDTH - sum(minw), [p - m for p, m in zip(pref, minw, strict=True)]
        widths = [m + spare * e / sum(extra) for m, e in zip(minw, extra, strict=True)]
    widths = [round(w) for w in widths]
    widths[-1] += TEXT_WIDTH - sum(widths)
    return widths


def blocks(text: str) -> list[str]:
    return [b.strip("\n") for b in re.split(r"\n\s*\n", text) if b.strip()]


def table_rows(block: str) -> list[list[str]]:
    rows = []
    for line in block.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-+:?", c) for c in cells):
            continue
        rows.append(cells)
    return rows


def cover(lines: list[str], doc: Doc) -> str:
    """The cover page, laid out like the template's."""
    lines = [x.strip() for x in lines if x.strip()]
    inst, report, title, author, city, date = lines[:3], lines[3], lines[4], lines[5], lines[6], lines[7]
    out = []
    for i, t in enumerate(inst):
        out.append(para(run(t, bold=i < 2, caps=True), jc="center", first=0, after=200))
    out.append(para(run(report), jc="center", first=0, before=2600, after=600))
    m = re.fullmatch(r"\*\*(.+?): (.+)\*\*", title)
    main, sub = (m.group(1), m.group(2)) if m else (plain(title), "")
    out.append(para(inline(f"**{main}:**"), jc="center", first=0, after=120))
    if sub:
        out.append(para(inline(sub), jc="center", first=0, after=0))
    m = re.fullmatch(r"(.+?)\s+(\S+@\S+)", author)
    if m:
        rid = f"rIdLink{len(doc.links) + 1}"
        doc.links.append((rid, f"mailto:{m.group(2)}"))
        author_runs = (run(m.group(1) + " ", size=20, bold=True)
                       + f'<w:hyperlink r:id="{rid}" w:history="1"><w:r><w:rPr><w:rStyle w:val="Hyperlink"/>'
                       f'<w:b w:val="0"/><w:sz w:val="20"/><w:szCs w:val="20"/></w:rPr>'
                       f'<w:t>{escape(m.group(2))}</w:t></w:r></w:hyperlink>')
    else:
        author_runs = run(author, size=20, bold=True)
    out.append(para(author_runs, jc="center", first=0, before=1800, after=0))
    # City and date sit at the foot of the cover. They are ordinary paragraphs pushed down
    # by spacing (a frame would be anchored to the next page's first paragraph).
    out.append(para(run(city), jc="center", first=0, before=COVER_GAP, after=200))
    out.append(para(run(date), jc="center", first=0, before=0, after=0))
    return "".join(out)


def build(pages: dict) -> tuple[str, Doc, str]:
    md = SOURCE.read_text(encoding="utf-8")
    first = md.index("\n# ")
    doc = Doc(pages)
    parts = re.split(r"\n(?=# )", md[first + 1:])
    sections = []
    for part in parts:
        head, _, rest = part.partition("\n")
        sections.append((head[2:].strip(), rest))

    # First pass over the text sections, so the Sumário and the lists know their entries.
    text_xml = []
    for title, rest in sections:
        if title in PRETEXT:
            continue
        center = not re.match(r"\d", title)
        text_xml.append(doc.heading(1, title, center=center))
        in_refs = title == "REFERÊNCIAS"
        pending = None                                   # caption kind waiting for its table
        for b in blocks(rest):
            if b.startswith("## "):
                text_xml.append(doc.heading(2, b[3:].strip()))
            elif b.startswith("|"):
                text_xml.append(doc.table(table_rows(b), pending or "Tabela"))
                pending = None
            elif b.startswith("!["):
                path = ARTICLE / re.search(r"\((.+?)\)", b).group(1)
                text_xml.append(doc.image(path))
            elif (m := CAPTION.match(b)):
                kind = m.group(1)
                label = f"{kind} {m.group(2)} – {plain(m.group(3))}"
                doc.captions.append((kind, label))
                pending = kind
                text_xml.append(para(run(f"{kind} {m.group(2)} – ", bold=True, size=20)
                                     + inline(m.group(3), size=20), jc="center", first=0,
                                     before=240, after=120, keep_next=True))
            elif b.startswith("Fonte:"):
                text_xml.append(para(inline(b, size=20), jc="left", first=0, before=60, after=240,
                                     keep_lines=True))
            elif in_refs:
                text_xml.append(para(inline(b), jc="left", first=0, after=240))
            else:
                text_xml.append(para(inline(b), first=709, after=120,
                                     jc="left" if "https://" in b else "both"))

    pre = [cover(md[:first].splitlines(), doc)]
    for title, rest in sections:
        if title not in PRETEXT:
            continue
        pre.append(doc.pretext_title(title))
        if title == "RESUMO":
            for b in blocks(rest):
                if b.startswith("Palavras-chave:"):
                    words = b[len("Palavras-chave:"):].strip()
                    pre.append(para(run("Palavras-chave:", bold=True) + inline(" " + words),
                                    jc="both", left=1985, hanging=1985, before=240))
                else:
                    pre.append(para(inline(b), first=0, after=120))
        elif title == "LISTA DE ILUSTRAÇÕES":
            pre.append(doc.list_of(("Figura", "Quadro")))
        elif title == "LISTA DE TABELAS":
            pre.append(doc.list_of(("Tabela",)))
        elif title == "LISTA DE ABREVIATURAS E SIGLAS":
            tab = '<w:tabs><w:tab w:val="left" w:pos="1418"/></w:tabs>'
            for row in table_rows(next(b for b in blocks(rest) if b.startswith("|")))[1:]:
                pre.append(para(run(plain(row[0])) + f"<w:r>{rpr()}<w:tab/></w:r>" + inline(row[1]),
                                jc="left", left=1418, hanging=1418, after=60, tabs=tab))
        elif title == "SUMÁRIO":
            pre.append(doc.summary())
    return "".join(pre), doc, "".join(text_xml)


def assemble(pages: dict, out: Path = OUTPUT) -> Path:
    pre, doc, text = build(pages)
    with zipfile.ZipFile(TEMPLATE) as z:
        files = {i.filename: z.read(i.filename) for i in z.infolist() if not i.filename.endswith("/")}
    tpl = files["word/document.xml"].decode("utf-8")
    head = tpl[:tpl.index("<w:body>") + len("<w:body>")]
    sects = re.findall(r"<w:sectPr\b.*?</w:sectPr>", tpl, flags=re.S)
    first_sect, last_sect = sects[0], sects[-1]
    last_sect = re.sub(r"<w:pgNumType[^>]*/>", "", last_sect)   # count pages from the cover
    body = (pre + f"<w:p><w:pPr>{first_sect}</w:pPr></w:p>" + text + last_sect)
    files["word/document.xml"] = (head + body + "</w:body></w:document>").encode("utf-8")

    rels = files["word/_rels/document.xml.rels"].decode("utf-8")
    rels = re.sub(r'<Relationship Id="rId[89]"[^>]*mailto:[^>]*/>', "", rels)
    extra = "".join(
        f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/{png.name}"/>'
        for rid, png in doc.images)
    extra += "".join(
        f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="{escape(t)}" TargetMode="External"/>'
        for rid, t in doc.links)
    files["word/_rels/document.xml.rels"] = rels.replace("</Relationships>", extra + "</Relationships>").encode("utf-8")
    for _, png in doc.images:
        files[f"word/media/{png.name}"] = png.read_bytes()

    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    md = SOURCE.read_text(encoding="utf-8")
    author_line = next(x for x in md[:md.index("\n# ")].splitlines() if "@" in x)
    author = re.match(r"(.+?) \(", author_line).group(1)
    title = plain(next(x for x in md.splitlines() if x.startswith("**"))).split(":")[0]
    files["docProps/core.xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f"<dc:title>{escape(title.capitalize())}</dc:title><dc:creator>{escape(author)}</dc:creator>"
        f"<cp:lastModifiedBy>{escape(author)}</cp:lastModifiedBy><cp:revision>1</cp:revision>"
        f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>'
        f'<dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified></cp:coreProperties>'
    ).encode()

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        order = ["[Content_Types].xml"] + [f for f in files if f != "[Content_Types].xml"]
        for name in order:
            z.writestr(name, files[name])
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pages", type=Path, help="page numbers written by paginate.py")
    ap.add_argument("--out", type=Path, default=OUTPUT)
    args = ap.parse_args()
    pages = json.loads(args.pages.read_text()) if args.pages and args.pages.exists() else {}
    print(assemble(pages, args.out))


if __name__ == "__main__":
    main()
