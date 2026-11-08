"""Local library import and notation regeneration without model inference."""

from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO


def import_musicxml(content: bytes, filename: str, folder: Path):
    import music21
    import pretty_midi

    if filename.lower().endswith(".mxl"):
        with zipfile.ZipFile(BytesIO(content)) as archive:
            if sum(f.file_size for f in archive.infolist()) > 10 * 1024 * 1024:
                raise ValueError("解压后的乐谱超过 10 MB")
            container = ET.fromstring(archive.read("META-INF/container.xml"))
            rootfile = next(e for e in container.iter() if e.tag.split("}")[-1] == "rootfile")
            content = archive.read(rootfile.attrib["full-path"])
    if b"<!ENTITY" in content.upper():
        raise ValueError("乐谱包含不支持的 XML 实体")
    root = ET.fromstring(content)
    if root.tag != "score-partwise" or not root.findall("part"):
        raise ValueError("请选择有效的 MusicXML 钢琴乐谱")
    title = (
        root.findtext("work/work-title") or root.findtext("movement-title") or Path(filename).stem
    )
    score = music21.converter.parseData(ET.tostring(root, encoding="unicode"), format="musicxml")
    score.write("midi", fp=str(folder / "score.mid"))
    (folder / "score.musicxml").write_bytes(content)
    midi = pretty_midi.PrettyMIDI(str(folder / "score.mid"))
    _, tempi = midi.get_tempo_changes()
    bpm = float(tempi[0]) if len(tempi) else 120.0
    signature = midi.time_signature_changes[0] if midi.time_signature_changes else None
    return title.strip()[:160] or "未命名乐谱", {
        "duration": midi.get_end_time(),
        "bpm": bpm,
        "time_signature": f"{signature.numerator}/{signature.denominator}" if signature else "4/4",
        "note_count": sum(len(i.notes) for i in midi.instruments),
        "settings": {"source": "musicxml"},
    }


def rename_musicxml(folder: Path, title: str):
    path = folder / "score.musicxml"
    if not path.exists():
        return
    tree = ET.parse(path)
    root = tree.getroot()
    work = root.find("work")
    if work is None:
        work = ET.SubElement(root, "work")
    label = work.find("work-title")
    if label is None:
        label = ET.SubElement(work, "work-title")
    label.text = title
    movement = root.find("movement-title")
    if movement is not None:
        movement.text = title
    temporary = path.with_suffix(".xml.tmp")
    tree.write(temporary, encoding="utf-8", xml_declaration=True)
    temporary.replace(path)
