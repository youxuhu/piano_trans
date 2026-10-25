"""灵谱 后端 —— FastAPI 服务

接口：
  POST /api/transcribe   上传音频文件，返回 MusicXML 二进制（alphaTab 可直接渲染）
  GET  /api/health       健康检查

内部流程：
  音频 → basic-pitch → pretty_midi 音符事件 → music21 → MusicXML
（不经过 MIDI 文件解析：music21 会把 pretty_midi 的 220tpb MIDI 时序读塌缩）
"""
from __future__ import annotations

import os
import uuid
import time
from typing import Optional

import numpy as np
import librosa
import music21
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from basic_pitch.inference import predict as _bp_predict
from basic_pitch import ICASSP_2022_MODEL_PATH as _BP_MODEL

# ---------- 路径 & 配置 ----------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, 'output')
os.makedirs(OUTPUT_DIR, exist_ok=True)

SAMPLE_RATE = 16000
DEVICE = 'cpu'    # demo 用 CPU，约 30s / 10s 音频

# ---------- 模型单例（首次请求时加载） ----------
_transcriber = None
_transcribe_load_begin = None


def _get_transcriber() -> None:
    """basic-pitch 用 onnxruntime 加载模型（包自带权重，无需显式构造单例）。
    这里保留占位，仅用于记录加载耗时。"""
    global _transcriber, _transcribe_load_begin
    if _transcriber is None:
        _transcribe_load_begin = time.time()
        # basic-pitch 首次 predict 时会自动加载 ONNX 模型（约几秒）
        _transcriber = True
    return _transcriber


# ---------- FastAPI ----------


# ---------- 乐谱构建 & 清洗 ----------
# 注意：basic-pitch 的 pretty_midi 写出的 MIDI 分辨率为 220 tpb，music21.converter.parse
# 会把它读成 ~3-4 拍（时序塌缩），导致整首曲子被塞进 1 个小节。因此这里不经过 MIDI 文件，
# 而是直接用 pretty_midi 的音符事件（秒）按 BPM 换算成拍，喂给 music21 建谱。

_DEFAULT_BPM = 120.0


def _estimate_timing(notes):
    """从音符 onset(秒) 估计 (bpm, meter_num)。
    bpm：在候选区间内，找出让所有 onset 对齐到"拍或其半拍"栅格残差最小、且取最慢可行拍的速度
        （避免把一拍单词格误判成倍速，或选到非规整值）。
    meter：仅对落在拍栅格上的 onset，比较按 3/两拍/4 分组时"重拍命中 - 非重拍命中"的强弱，选最规整者。
    异常回退 (120, 4)。"""
    ts = sorted(float(n.start) for n in notes)
    if len(ts) < 4:
        return _DEFAULT_BPM, 4
    try:
        import numpy as np
        ts = np.array(ts)
        ts = ts - ts[0]
        # --- tempo：优先让 onset 落在整拍栅格；同残差时取更慢(更大 T)，避免八度加倍 ---
        best_res, best_bpm = 1e9, _DEFAULT_BPM
        for bpm in range(55, 201):
            p = 60.0 / bpm
            frac = np.mod(ts / p, 1.0)
            frac = np.minimum(frac, 1.0 - frac)          # 到最近整拍的距离
            res = float(np.median(frac))
            if res < best_res - 1e-9:
                best_res, best_bpm = res, bpm
            elif abs(res - best_res) <= 1e-9 and bpm < best_bpm:
                best_bpm = bpm
        bpm = best_bpm
        p = 60.0 / bpm
        idx = [int(round(t / p)) for t in ts.tolist()]
        maxidx = max(idx)
        # --- meter：仅统计落在拍梯形内的 onset ---
        onbeat = [i for i, t in zip(idx, ts.tolist())
                  if min(np.mod(t / p, 1.0), 1 - np.mod(t / p, 1.0)) < 0.15]
        if not onbeat:
            return int(bpm), 4
        scores = {}
        for m in (4, 3, 2):
            total_down = max(1, maxidx // m + 1)
            total_non = max(1, maxidx + 1 - total_down)
            if total_non <= 0:
                scores[m] = -1
                continue
            down = sum(1 for i in onbeat if i % m == 0)
            non = sum(1 for i in onbeat if i % m != 0)
            scores[m] = (down / total_down) - 0.4 * (non / total_non)
        # 默认偏 4/4；仅当 3 或 2 显著更规整时才切换，避免无强弱时误判
        best_m, best_s = 4, scores[4]
        for m in (3, 2):
            if scores[m] > best_s + 0.2:
                best_m, best_s = m, scores[m]
        return int(bpm), int(best_m)
    except Exception:
        return _DEFAULT_BPM, 4


def _build_events(notes, note_events, bpm=_DEFAULT_BPM):
    """pretty_midi Note(秒,pitch) + basic-pitch note_events(含 confidence)
    -> [(offset拍, midi, dur拍, conf)]。
    置信度用来解决 basic-pitch 同一时刻报出基音+五度/泛音的问题：从中选主导音。"""
    spb = 60.0 / bpm
    conf = {}
    if note_events is not None:
        try:
            for r in note_events.itertuples():
                conf[(round(r.start_time_s, 3), int(r.pitch_midi))] = \
                    float(getattr(r, 'confidence', 0.0))
        except Exception:
            conf = {}
    out = []
    for n in notes:
        sec = float(n.start)
        out.append((sec / spb, int(n.pitch), float(n.end - n.start) / spb,
                    conf.get((round(sec, 3), int(n.pitch)), 0.0)))
    return out


# ---- 通用乐谱清洗参数（模型无关，换曲子/换模型都复用，改这里即可调节）----
_MELODY_MODE = True      # 单声部优先：同一时刻多音只保留主导音（丢五度/泛音双音）
_QUANT_GRID = 0.5        # 起拍 & 时值量化网格（拍），最小八分音符，滤掉 16/32 分碎音
_WARMUP = 0.5            # 丢弃 offset < 0.5 拍（预热/和音塌）


def _clean_events(ev, grid=_QUANT_GRID, monophonic=_MELODY_MODE, warmup=_WARMUP):
    """通用乐谱清洗：去重 → [单声部提取] → 网格量化 → 去预热/清零时值。"""
    # 1) 同起拍同音高去重
    seen = set()
    flat = []
    for q, p, d, c in sorted(ev, key=lambda x: (round(x[0], 3), -x[3])):
        k = (round(q, 3), p)
        if k in seen:
            continue
        seen.add(k)
        flat.append([q, p, d, c])

    # 2) 单声部提取：同一 onset 容差内的多个音，只保 confidence 最高的主导音
    if monophonic:
        EPS = grid * 0.5
        groups = []
        for it in sorted(flat, key=lambda x: x[0]):
            if groups and (it[0] - groups[-1][0][0]) <= EPS:
                groups[-1].append(it)
            else:
                groups.append([it])
        flat = [max(g, key=lambda x: x[3]) for g in groups]

    # 3) 起拍 & 时值量化到 grid 网格 → 消除附点/16/32 分碎值
    def snap(v):
        return round(v / grid) * grid
    flat = [[snap(o), int(p), snap(d), c] for (o, p, d, c) in flat]

    # 4) 去预热期 + 量化后时值为 0 的事件
    flat = [x for x in flat if x[0] >= warmup and x[2] > 0.0]

    # 5) 量化后再去重（可能撞在同一拍同音高）
    seen2 = set()
    res = []
    for o, p, d, _c in sorted(flat, key=lambda x: (round(x[0], 3), x[1])):
        k = (round(o, 3), int(p))
        if k in seen2:
            continue
        seen2.add(k)
        res.append([o, int(p), d])
    return res


def _score_from_events(notes, note_events, title, bpm=_DEFAULT_BPM, meter_num=4):
    """从 pretty_midi 音符事件直接建 music21 Score（绕开 music21 的 MIDI 时序 bug）。"""
    ev = _build_events(notes, note_events, bpm=bpm)
    kept = _clean_events(ev)

    sc = music21.stream.Stream()
    sc.insert(0, music21.meter.TimeSignature(f'{meter_num}/4'))
    sc.insert(0, music21.tempo.MetronomeMark(number=int(bpm)))
    for q, p, d in sorted(kept, key=lambda x: x[0]):
        sc.insert(
            float(q),
            music21.note.Note(
                pitch=music21.pitch.Pitch(midi=p),
                duration=music21.duration.Duration(quarterLength=d),
            ),
        )

    # makeMeasures() 按 4/4 自动切小节、在每个 measure 头写 <attributes>
    sc = sc.makeMeasures()
    sc.insert(0, music21.metadata.Metadata(title=title))

    print(f'[clean] events={len(ev)} -> kept={len(kept)} measures={len(list(sc.recurse().getElementsByClass(music21.stream.Measure)))}')
    return sc

app = FastAPI(title='灵谱后端', version='0.1.0')

# CORS：允许 vite 默认 dev 端口
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        'http://localhost:5173',
        'http://localhost:5174',
        'http://127.0.0.1:5173',
        'http://127.0.0.1:5174',
        '*',   # demo 放宽
    ],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)


@app.get('/api/health')
def health():
    return JSONResponse({
        'status': 'ok',
        'model_loaded': _transcriber is not None,
        'device': DEVICE,
    })


# 允许的音频扩展名
_ALLOWED_EXTS = {'.wav', '.mp3', '.m4a', '.ogg', '.flac', '.aac', '.webm'}


@app.post('/api/transcribe')
async def transcribe(audio: UploadFile = File(...)):
    # ① 校验扩展名
    name = audio.filename or 'audio'
    ext = os.path.splitext(name)[1].lower()
    if ext not in _ALLOWED_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f'不支持的文件类型: {ext or "(无)"}。允许：{", ".join(sorted(_ALLOWED_EXTS))}',
        )

    # ② 把上传的音频先存到临时文件（librosa 需要文件路径）
    task_id = uuid.uuid4().hex[:12]
    tmp_audio = os.path.join(OUTPUT_DIR, f'_{task_id}{ext}')
    midi_path = os.path.join(OUTPUT_DIR, f'_{task_id}.mid')
    xml_path = os.path.join(OUTPUT_DIR, f'_{task_id}.musicxml')

    try:
        content = await audio.read()
        if not content:
            raise HTTPException(status_code=400, detail='上传文件为空')

        with open(tmp_audio, 'wb') as f:
            f.write(content)

        # ③ 用 librosa 读成 16kHz 单声道 numpy 数组
        y, sr = librosa.load(tmp_audio, sr=SAMPLE_RATE, mono=True)
        if y.size == 0:
            raise HTTPException(status_code=400, detail='音频解码失败（可能是损坏文件）')

        duration = float(y.size) / SAMPLE_RATE
        print(f'[transcribe] task={task_id} audio={name} dur={duration:.2f}s sr={sr}')

        # ④ 跑转谱 → MIDI（basic-pitch：ONNX 推理，直接吃音频文件路径）
        t0 = time.time()
        if os.path.exists(midi_path):
            os.remove(midi_path)
        # basic-pitch 直接吃音频文件路径，返回 (model_output, pretty_midi, note_events)
        _, bp_midi, bp_notes = _bp_predict(tmp_audio, _BP_MODEL)
        bp_midi.write(midi_path)
        dt_trans = time.time() - t0
        print(f'[transcribe] task={task_id} midi done in {dt_trans:.1f}s (basic-pitch, notes={len(bp_notes)})')

        # ⑤ 直接拿 pretty_midi 音符事件建 MusicXML（绕开 music21 的 MIDI 时序塌缩 bug）
        t1 = time.time()
        # 拍号 & BPM 校正（用 onset 秒估计，替代不可靠的 get_tempo_changes）
        bpm, meter_num = _estimate_timing(bp_midi.instruments[0].notes)
        print(f'[timing] task={task_id} bpm={bpm} meter={meter_num}/4')
        score = _score_from_events(
            bp_midi.instruments[0].notes,
            bp_notes,
            os.path.splitext(name)[0] or 'Transcribed',
            bpm=bpm,
            meter_num=meter_num,
        )
        score.write('musicxml', fp=xml_path)

        # music21 只在 measure 1 写 <attributes>，alphaTab v1.8.4 要求每个 measure 都显式带
        _ensure_attrs_every_measure(xml_path)

        dt_xml = time.time() - t1
        print(f'[transcribe] task={task_id} musicxml done in {dt_xml:.1f}s → {xml_path}')

        # ⑥ 返回 MusicXML 二进制流
        def _stream():
            with open(xml_path, 'rb') as xf:
                while True:
                    chunk = xf.read(64 * 1024)
                    if not chunk:
                        break
                    yield chunk
            # 读完后清理临时音频（保留 MIDI + XML 便于调试）
            for p in (tmp_audio,):
                if os.path.exists(p):
                    try: os.remove(p)
                    except OSError: pass

        total_dt = time.time() - t0
        return StreamingResponse(
            _stream(),
            media_type='application/xml',
            headers={
                'Content-Disposition': f'attachment; filename="{task_id}.musicxml"',
                'X-Transcribe-Task': task_id,
                'X-Transcribe-Duration': f'{duration:.2f}',
                'X-Transcribe-MidiElapsed': f'{dt_trans:.2f}',
                'X-Transcribe-XmlElapsed': f'{dt_xml:.2f}',
                'X-Transcribe-TotalElapsed': f'{total_dt:.2f}',
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        for p in (tmp_audio, midi_path, xml_path):
            if os.path.exists(p):
                try: os.remove(p)
                except OSError: pass
        print(f'[transcribe] task={task_id} ERROR: {e!r}')
        raise HTTPException(status_code=500, detail=f'转谱失败: {e}')




import re as _re

def _ensure_attrs_every_measure(xml_path):
    """music21 默认只在第一个 measure 写 <attributes>（MusicXML 规范允许省略未变属性），
    但 alphaTab v1.8.4 的 MusicXmlImporter 会在 _parseNote 里崩（ensureBeat 拿不到 timeSig）。
    解决：把 measure 1 的 <attributes> 块复制到所有后续 measure 里。"""
    with open(xml_path, encoding='utf-8') as f:
        xml = f.read()

    # 找 measure 1 的 attributes 块
    m1 = _re.search(r'<measure number="1">(.*?)</measure>', xml, _re.DOTALL)
    if not m1:
        return
    attr_match = _re.search(r'(<attributes>.*?</attributes>)', m1.group(1), _re.DOTALL)
    if not attr_match:
        return
    attrs_block = attr_match.group(1)

    # 把每个后续 measure（编号 >= 2）里如果没有 attributes 块，就插一个
    def _patch(m):
        body = m.group(2)
        if '<attributes>' in body:
            return m.group(0)
        return m.group(1) + attrs_block + m.group(2) + m.group(3)

    xml_new = _re.sub(
        r'<measure number="(\d+)">(.*?)</measure>',
        lambda mm: ('<measure number="' + mm.group(1) + '">' + attrs_block + mm.group(2) + '</measure>')
                   if int(mm.group(1)) >= 2 and '<attributes>' not in mm.group(2)
                   else mm.group(0),
        xml, flags=_re.DOTALL,
    )

    if xml_new != xml:
        with open(xml_path, 'w', encoding='utf-8') as f:
            f.write(xml_new)
        print('[xml-patch] inserted <attributes> into all measures')


if __name__ == '__main__':
    import uvicorn
    uvicorn.run('main:app', host='127.0.0.1', port=8000, reload=False)
