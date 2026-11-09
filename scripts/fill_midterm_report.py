"""Fill the 2026 mid-term review docx from the Markdown source.

The template in ``docs/材料备份/中期检查报告_原始模板.docx`` keeps its own
page setup, tables, shading, footer and instruction text.  This script only
rewrites the target runs inside ``word/document.xml``:

* basic-info blanks reuse the cell paragraph's own ``w:pPr`` and a 12 pt
  ``Times New Roman`` / ``宋体`` run (``w:sz=24``), exactly like the fields the
  template already fills in;
* body paragraphs are cloned from the template's own placeholder ``w:pPr``
  (``before=0 after=0 line=240 auto``) plus a 2-character first-line indent,
  and use a run property string copied out of the template itself;
* the template's own ``w:sym Wingdings 2`` checkbox runs are kept; the two
  selected boxes switch from ``00A3`` (□) to ``00FE`` (☑) and nothing else
  about them changes;
* nothing else is touched, every other zip member is written back byte-exact.

Usage:  python3 scripts/fill_midterm_report.py
"""

from __future__ import annotations

import re
import shutil
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "docs" / "材料备份" / "中期检查报告_原始模板.docx"
SOURCE = ROOT / "docs" / "中期检查报告-正文.md"
OUTPUT = ROOT / "中期检查报告-胡有绪.docx"

# Paragraph ids in the template that this script fills or replaces.
FIELDS = {
    "项目名称": "341D7DB0",
    "项目编号": "554062AC",
    "立项年度": "0CEC1E9D",
}
LEADER_FIELDS = ["6F2BACCC", "036E68F8", "516B4651"]
ADVISOR_FIELDS = ["3F6FC2C9", "0F377CC8", "395D06D9", "531DAE66"]
RESULT_CELLS = ["4E70B9A7", "5D336EEF", "477FEA19", "640D4971", "65387DBD"]
MEMBER_ANCHOR = "张三，学号，学院，电话"
MEMBER_TEMPLATE_PARA = "6F2BACCC"  # any filled body paragraph, only for its run format

# Heading text -> key used in the Markdown file.
META_KEYS = {
    "项目名称",
    "项目编号",
    "立项年度",
    "负责人",
    "指导教师",
    "成员",
    "成果登记",
}

SECTIONS = [
    ("一、项目进展情况", "一"),
    ("二、存在的问题和不足及拟采取的应对措施", "二"),
    ("三、经费使用情况", "三"),
    ("四、阶段性成果", "四"),
    ("五、项目后期规划", "五"),
]

CHECKBOX_BLANK = '<w:sym w:font="Wingdings 2" w:char="00A3"/>'
CHECKBOX_TICKED = '<w:sym w:font="Wingdings 2" w:char="00FE"/>'

INDENT = '<w:ind w:firstLineChars="200" w:firstLine="480"/>'

# Vertical alignment of the section-heading cells in the review table.
# The template uses "center"; a section row that splits over two pages can then
# render its heading away from the start of the section (or lose it in some
# previewers), so "top" is kept as a one-word switch.
HEADING_VALIGN = "center"

CJK = r"\u4e00-\u9fff\u3000-\u303f\uff00-\uffef"


def _is_cjk(char: str) -> bool:
    return bool(char) and re.match(rf"[{CJK}]", char) is not None


def normalise(text: str) -> str:
    """Drop the space between a standalone number and a Chinese character.

    The template and the application form write "2025年11月", "10000元",
    "10秒"; spaces are kept between Chinese text and Latin words ("采用 PyTorch
    框架") and inside Latin tokens ("RTX 5090 D v2").
    """
    titles = [m.span() for m in re.finditer(r"《[^》]*》", text)]
    out: list[str] = []
    for index, char in enumerate(text):
        if any(start <= index < end for start, end in titles):
            out.append(char)
            continue
        if char == " " and index and index + 1 < len(text):
            previous, following = text[index - 1], text[index + 1]
            if _is_cjk(previous) and following.isdigit():
                continue
            if previous.isdigit() and _is_cjk(following):
                start = index - 1
                while start - 1 >= 0 and text[start - 1].isdigit():
                    start -= 1
                if not (start - 1 >= 0 and text[start - 1].isalpha()):
                    continue
        out.append(char)
    return "".join(out)


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------------------------------------------------------------- source text


def parse_source(path: Path) -> tuple[dict[str, list[str]], dict[str, list[tuple[str, str]]]]:
    """Return (meta, sections) where sections[key] = [(kind, text), ...]."""
    meta: dict[str, list[str]] = {}
    sections: dict[str, list[tuple[str, str]]] = {}
    current: list[tuple[str, str]] | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("# "):
            continue
        if line.startswith("## "):
            num = line[3:].strip()[0]
            if num not in {key for _, key in SECTIONS}:
                raise SystemExit(f"unknown section line: {line}")
            current = sections.setdefault(num, [])
            continue
        if line.startswith("### "):
            if current is None:
                raise SystemExit("sub-heading outside a section")
            current.append(("sub", line[4:].strip()))
            continue
        if current is None:
            key, _, value = line.partition("：")
            key = key.strip()
            if key not in META_KEYS:
                continue  # explanatory prose above the metadata block
            meta.setdefault(key, []).append(value.strip())
            continue
        current.append(("body", line))
    return meta, sections


# ------------------------------------------------------------ xml primitives


def find_paragraph(xml: str, para_id: str) -> tuple[int, int]:
    pattern = re.compile(r'<w:p [^>]*w14:paraId="%s"[^>]*/>' % para_id)
    match = pattern.search(xml)
    if match:
        return match.span()
    pattern = re.compile(r'<w:p [^>]*w14:paraId="%s"[^>]*>.*?</w:p>' % para_id, re.S)
    match = pattern.search(xml)
    if not match:
        raise SystemExit(f"paragraph {para_id} not found")
    return match.span()


def paragraph_parts(block: str) -> tuple[str, str, str]:
    """Split a paragraph block into (opening tag, pPr, first run rPr)."""
    open_end = block.index(">") + 1
    opening = block[:open_end]
    ppr_match = re.search(r"<w:pPr>.*?</w:pPr>", block, re.S)
    ppr = ppr_match.group(0) if ppr_match else ""
    rest = block[open_end:]
    rpr_match = re.search(r"<w:rPr>.*?</w:rPr>", rest, re.S)
    rpr = rpr_match.group(0) if rpr_match else ""
    return opening, ppr, rpr


def replace_paragraph(xml: str, para_id: str, text: str, rpr: str) -> str:
    start, end = find_paragraph(xml, para_id)
    opening, ppr, own_rpr = paragraph_parts(xml[start:end])
    use = own_rpr or rpr
    new = (
        f'{opening}{ppr}<w:r>{use}'
        f'<w:t xml:space="preserve">{esc(text)}</w:t></w:r></w:p>'
    )
    return xml[:start] + new + xml[end:]


def find_cell(xml: str, anchor: str) -> tuple[int, int]:
    index = xml.index(anchor)
    start = xml.rindex("<w:tc>", 0, index)
    end = xml.index("</w:tc>", index)
    return start, end + len("</w:tc>")


def cell_properties(cell: str) -> str:
    match = re.match(r"<w:tc>(<w:tcPr>.*?</w:tcPr>)", cell, re.S)
    if not match:
        raise SystemExit("cell without w:tcPr")
    return match.group(1)


def drop_paragraph(xml: str, para_id: str) -> str:
    start, end = find_paragraph(xml, para_id)
    return xml[:start] + xml[end:]


def align_heading_cell(xml: str, heading: str, valign: str) -> str:
    index = xml.index(">" + heading)
    start = xml.rindex("<w:tc>", 0, index)
    end = xml.index("</w:tc>", index) + len("</w:tc>")
    cell = xml[start:end]
    if '<w:vAlign w:val="center"/>' not in cell:
        raise SystemExit(f"heading cell of {heading} has no centred vAlign")
    cell = cell.replace('<w:vAlign w:val="center"/>', f'<w:vAlign w:val="{valign}"/>', 1)
    return xml[:start] + cell + xml[end:]


def section_cell(xml: str, heading: str) -> tuple[int, int]:
    index = xml.index(">" + heading)
    heading_end = xml.index("</w:tc>", index)
    start = xml.index("<w:tc>", heading_end)
    end = xml.index("</w:tc>", start)
    return start, end + len("</w:tc>")


# --------------------------------------------------------------- generation


def body_paragraph(
    text: str, ppr: str, rpr: str, bold: bool = False, indent: bool = True
) -> str:
    """Build a paragraph with the template's own spacing and run format."""
    text = normalise(text)
    run_rpr = rpr.replace('<w:b w:val="0"/>', "<w:b/>") if bold else rpr
    inner = ppr.removeprefix("<w:pPr>").removesuffix("</w:pPr>")
    inner = re.sub(r"<w:rPr>.*?</w:rPr>", "", inner, flags=re.S)
    add = "" if (bold or not indent) else INDENT
    return (
        f"<w:p><w:pPr>{inner}{add}</w:pPr><w:r>{run_rpr}"
        f'<w:t xml:space="preserve">{esc(text)}</w:t></w:r></w:p>'
    )


def main() -> int:
    meta, sections = parse_source(SOURCE)
    with zipfile.ZipFile(TEMPLATE) as archive:
        members = {info.filename: archive.read(info.filename) for info in archive.infolist()}
        order = [info.filename for info in archive.infolist()]
    xml = members["word/document.xml"].decode("utf-8")

    # Reuse the template's own body run format (12 pt, Times New Roman / 宋体),
    # and the pPr of the empty paragraphs inside the content cells.
    _, _, body_rpr = paragraph_parts(xml[slice(*find_paragraph(xml, MEMBER_TEMPLATE_PARA))])
    if '<w:sz w:val="24"/>' not in body_rpr:
        raise SystemExit(f"unexpected template body run format: {body_rpr}")
    _, body_ppr, _ = paragraph_parts(
        xml[slice(*find_paragraph(xml, "5DF34145"))]  # empty paragraph in a content cell
    )
    if 'w:line="240"' not in body_ppr or 'w:after="0"' not in body_ppr:
        raise SystemExit(f"unexpected template body paragraph spacing: {body_ppr}")

    # --- basic information -------------------------------------------------
    name = meta.get("项目名称")
    number = meta.get("项目编号")
    year = meta.get("立项年度")
    if not (name and number and year):
        raise SystemExit("项目名称 / 项目编号 / 立项年度 missing in source")
    xml = replace_paragraph(xml, FIELDS["项目名称"], normalise(name[0]), body_rpr)
    for spare in ("616B7407", "41060AD4"):  # keep the row one line high
        xml = drop_paragraph(xml, spare)
    xml = replace_paragraph(xml, FIELDS["项目编号"], number[0], body_rpr)
    xml = replace_paragraph(xml, FIELDS["立项年度"], year[0], body_rpr)

    leader = meta.get("负责人", [])
    if len(leader) != 3:
        raise SystemExit("负责人 needs exactly three lines")
    for para_id, text in zip(LEADER_FIELDS, leader):
        xml = replace_paragraph(xml, para_id, text, body_rpr)

    advisor = meta.get("指导教师", [])
    if len(advisor) != 4:
        raise SystemExit("指导教师 needs exactly four lines")
    for para_id, text in zip(ADVISOR_FIELDS, advisor):
        xml = replace_paragraph(xml, para_id, text, body_rpr)

    # checkboxes: 创新训练项目 and 校级 (chars stay in the template's Wingdings 2 run)
    def tick(anchor_text: str, para_id: str) -> None:
        nonlocal xml
        start, end = find_paragraph(xml, para_id)
        block = xml[start:end]
        if CHECKBOX_BLANK not in block:
            raise SystemExit(f"blank checkbox not found next to {anchor_text}")
        block = block.replace(CHECKBOX_BLANK, CHECKBOX_TICKED, 1)
        if CHECKBOX_TICKED not in block:
            raise SystemExit(f"checkbox not ticked next to {anchor_text}")
        xml = xml[:start] + block + xml[end:]

    tick("创新训练项目", "23F4F9B7")
    tick("校    级", "6685FF8B")

    # --- project members ---------------------------------------------------
    start, end = find_cell(xml, MEMBER_ANCHOR)
    cell = xml[start:end]
    props = cell_properties(cell)
    lines = meta.get("成员", [])
    if not lines:
        raise SystemExit("成员 missing in source")
    member_paras = "".join(
        body_paragraph(line, body_ppr, body_rpr, indent=False) for line in lines
    )
    filler = body_paragraph("", body_ppr, body_rpr, indent=False)
    xml = xml[:start] + f"<w:tc>{props}{member_paras}{filler}</w:tc>" + xml[end:]

    # --- mid-term review sections -----------------------------------------
    for heading, key in SECTIONS:
        items = sections.get(key)
        if not items:
            raise SystemExit(f"section {key} missing in source")
        paragraphs = "".join(
            body_paragraph(text, body_ppr, body_rpr, bold=(kind == "sub"))
            for kind, text in items
        )
        start, end = section_cell(xml, heading)
        props = cell_properties(xml[start:end])
        xml = xml[:start] + f"<w:tc>{props}{paragraphs}</w:tc>" + xml[end:]
        if HEADING_VALIGN != "center":
            xml = align_heading_cell(xml, heading, HEADING_VALIGN)

    # the commitment heading must not be orphaned at the bottom of a page
    xml = xml.replace(
        '<w:pPr><w:spacing w:before="280" w:after="120"/></w:pPr><w:r>'
        '<w:rPr><w:rFonts w:hint="eastAsia" w:ascii="Times New Roman" '
        'w:hAnsi="Times New Roman" w:eastAsia="黑体"/><w:b/><w:sz w:val="28"/>'
        '<w:lang w:val="en-US" w:eastAsia="zh-CN"/></w:rPr><w:t>四、</w:t>',
        '<w:pPr><w:keepNext/><w:spacing w:before="280" w:after="120"/></w:pPr><w:r>'
        '<w:rPr><w:rFonts w:hint="eastAsia" w:ascii="Times New Roman" '
        'w:hAnsi="Times New Roman" w:eastAsia="黑体"/><w:b/><w:sz w:val="28"/>'
        '<w:lang w:val="en-US" w:eastAsia="zh-CN"/></w:rPr><w:t>四、</w:t>',
        1,
    )

    # --- achievement registration row -------------------------------------
    row = meta.get("成果登记")
    if not row or len(row[0].split("|")) != 5:
        raise SystemExit("成果登记 needs five |-separated cells")
    for para_id, value in zip(RESULT_CELLS, row[0].split("|")):
        xml = replace_paragraph(xml, para_id, value, body_rpr)

    # --- checks ------------------------------------------------------------
    ElementTree.fromstring(xml)
    if "<w:pPr><w:pPr>" in xml or "<w:rPr><w:rPr>" in xml:
        raise SystemExit("nested paragraph/run properties produced")
    if xml.count('<w:sym w:font="Wingdings 2"') != 7:
        raise SystemExit("checkbox run count changed")
    if xml.count(CHECKBOX_TICKED) != 2:
        raise SystemExit("expected exactly two ticked checkboxes")
    if xml.count(CHECKBOX_BLANK) != 5:
        raise SystemExit(f"expected five blank checkboxes, found {xml.count(CHECKBOX_BLANK)}")
    red = [
        block
        for block in re.findall(r"<w:p [^>]*>.*?</w:p>", xml, re.S)
        if "FF0000" in block
    ]
    for block in red:
        text = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", block, re.S))
        if "手写签字" not in text:
            raise SystemExit(f"red placeholder formatting left: {text[:40]}")
    if xml.count("FF0000") != 4:
        raise SystemExit("unexpected amount of red formatting")
    leftovers = [
        block
        for block in re.findall(r"<w:p [^>]*>.*?</w:p>", xml, re.S)
        if "＿" in "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", block, re.S))
    ]
    for block in leftovers:
        text = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", block, re.S))
        if "签字" not in text and "日期" not in text:
            raise SystemExit(f"unfilled blank left: {text}")
    generated = re.findall(r"<w:p><w:pPr>.*?</w:pPr><w:r>.*?</w:r></w:p>", xml, re.S)
    if any("；" in block for block in generated):
        raise SystemExit("generated text still uses semicolons")
    if xml.count("<w:tbl>") != 4 or xml.count("<w:tbl>") != xml.count("</w:tbl>"):
        raise SystemExit("table structure changed")

    members["word/document.xml"] = xml.encode("utf-8")
    backup = OUTPUT.with_suffix(".backup.docx")
    if OUTPUT.exists():
        shutil.copyfile(OUTPUT, backup)
    with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED) as archive:
        for filename in order:
            archive.writestr(filename, members[filename])
    for filename, data in members.items():
        if filename != "word/document.xml" and TEMPLATE.exists():
            with zipfile.ZipFile(TEMPLATE) as template:
                if template.read(filename) != data:
                    raise SystemExit(f"unexpected change in {filename}")
    print(f"written {OUTPUT.relative_to(ROOT)}")
    print(
        f"paragraphs: {xml.count('<w:p ')}  ticked: {xml.count(CHECKBOX_TICKED)}"
        f"  blank: {xml.count(CHECKBOX_BLANK)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
