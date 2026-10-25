from __future__ import annotations
"""MIDI（音符事件列表） → AlphaTex 转换器

输入：模型输出的音符事件列表（秒级）
      [{'onset_time': float, 'offset_time': float, 'midi_note': int, 'velocity': int}]

输出：AlphaTex 字符串，喂给前端 alphaTab 直接渲染

五步流程：
  ① BPM 推断（用相邻 onset 间隔众数）
  ② 按拍号硬切小节
  ③ 每个音符换算时值 → 最近的合法拍数（附点处理）
  ④ midi_note → 字母（C4/F3/G5）
  ⑤ 输出头部指令 + | 切小节 + 休止符填充

一期简化：升降号 → 同名自然音；踏板 → 忽略；跨小节 → 截断 onset 所在小节。
"""

import math
from collections import Counter

# ① MIDI 音高 → 字母
_MIDI_TO_LETTER = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


def midi_to_name(midi_note):
    """midi_note 60 → 'C4'；升降号归到同名自然音"""
    letter = _MIDI_TO_LETTER[midi_note % 12]
    if len(letter) > 1:
        letter = letter[0]
    octave = midi_note // 12 - 1
    return f'{letter}{octave}'


# 合法拍数（四分音符 = 1 拍）及其 AlphaTex 时值写法
# 从大到小排列，匹配时找第一个"差 < 容差"的
_VALID_BEATS = [
    (4.0, '1'),     # 整音
    (3.0, '2.'),    # 附点二分
    (2.0, '2'),     # 二分
    (1.5, '4.'),    # 附点四分
    (1.0, '4'),     # 四分
    (0.75, '8.'),   # 附点八分
    (0.5, '8'),     # 八分
    (0.375, '16.'), # 附点十六分
    (0.25, '16'),   # 十六分
    (0.125, '32'),  # 三十二分
]


def beats_to_duration(beats, tolerance=0.12):
    """把拍数换算成 AlphaTex 时值字符串"""
    if beats <= 0:
        return None
    for valid, token in _VALID_BEATS:
        if abs(beats - valid) <= tolerance or beats >= valid * 0.85:
            return token
    return '32'


def infer_bpm(notes, min_interval=0.4, max_interval=1.5):
    """从相邻 onset 间隔推断 BPM（整数）

    min_interval 默认 0.4s = 150 BPM 封顶。真正的"一拍"不会短于这个值。
    过滤掉密集按键（快速旋律装饰音），只看大节奏间隔。
    """
    onsets = sorted([n['onset_time'] for n in notes])
    if len(onsets) < 2:
        return 90
    intervals = [onsets[i+1] - onsets[i] for i in range(len(onsets)-1)]
    intervals = [x for x in intervals if min_interval < x < max_interval]
    if not intervals:
        return 90
    rounded = [round(x * 20) / 20 for x in intervals]
    most_common = Counter(rounded).most_common(1)[0][0]
    bpm = round(60.0 / most_common)
    return max(30, min(240, bpm))


# 和弦：onset 差小于此秒数视作同一组
_CHORD_THRESHOLD_SEC = 0.08


def convert_to_alphatex(notes, title='transcribed', bpm=None,
                        numerator=4, denominator=4, debug=False):
    """
    把音符事件列表转成 AlphaTex 字符串。

    参数：
        notes        list[dict]  模型输出的音符事件（秒级时间戳）
        title        str         乐谱标题
        bpm          int         可选；不填则自动推断
        numerator    int         拍号分子（默认 4）
        denominator  int         拍号分母（默认 4）
        debug        bool        True 时在每小节前打印 debug 行
    """
    if not notes:
        return '\\title "' + title + '"\n\n\\clef treble\n\\tempo 90\nR1 |\n'

    # ① BPM
    if bpm is None:
        bpm = infer_bpm(notes)
    beat_sec = 60.0 / bpm
    bar_beats = numerator
    bar_sec = beat_sec * bar_beats

    if debug:
        dur = max(n['offset_time'] for n in notes)
        print(f'[midi_to_alphatex] BPM={bpm}, beat={beat_sec:.3f}s, bar={bar_sec:.3f}s')
        print(f'[midi_to_alphatex] 输入 {len(notes)} 个音符，音频总时长 ≈ {dur:.1f}s')

    # 音符预处理
    notes = [n for n in notes if n['offset_time'] > n['onset_time'] > -bar_sec]
    notes.sort(key=lambda n: (n['onset_time'], n['midi_note']))

    # ② 按小节归位
    bars = {}
    for n in notes:
        bar_idx = max(0, int(n['onset_time'] / bar_sec))
        bars.setdefault(bar_idx, []).append(n)

    max_bar = max(bars.keys())
    lines = [f'\\title "{title}"', '', '\\clef treble', f'\\tempo {bpm}']

    for bar_idx in range(max_bar + 1):
        bar_start = bar_idx * bar_sec
        bar_end = bar_start + bar_sec
        bar_notes = bars.get(bar_idx, [])

        # 音符转成拍数、时值、字母；截断跨小节的部分
        processed = []
        for n in bar_notes:
            onset_sec = max(n['onset_time'], bar_start)
            offset_sec = min(n['offset_time'], bar_end)
            dur_sec = max(0.01, offset_sec - onset_sec)
            onset_beats = (onset_sec - bar_start) / beat_sec
            dur_beats = dur_sec / beat_sec
            token = beats_to_duration(dur_beats)
            if token is None:
                continue
            processed.append({
                'onset_beats': onset_beats,
                'dur_beats': dur_beats,
                'token': token,
                'name': midi_to_name(n['midi_note']),
                'midi': n['midi_note'],
            })

        # 按 onset 归和弦组
        processed.sort(key=lambda p: (p['onset_beats'], p['midi']))
        chords = []
        cur = []
        for p in processed:
            if cur and (p['onset_beats'] - cur[0]['onset_beats']) <= \
                    (_CHORD_THRESHOLD_SEC / beat_sec):
                cur.append(p)
            else:
                if cur:
                    chords.append(cur)
                cur = [p]
        if cur:
            chords.append(cur)
        chords.sort(key=lambda g: g[0]['onset_beats'])

        if debug:
            print(f'\n--- bar {bar_idx} ({bar_start:.2f}s ~ {bar_end:.2f}s) ---')
            for c in chords:
                ns = '+'.join(p['name'] for p in c)
                print(f'  onset={c[0]["onset_beats"]:6.2f}拍  '
                      f'dur={c[0]["dur_beats"]:5.2f}拍  '
                      f'{ns}{c[0]["token"]}')

        # 组装 AlphaTex 片段
        bar_tokens = []
        cursor = 0.0
        for chord in chords:
            ob = chord[0]['onset_beats']
            db = chord[0]['dur_beats']
            # onset 前的休止符
            if ob > cursor + 0.05:
                bar_tokens.append(_rest_tokens(ob - cursor))
                cursor = ob
            names = [p['name'] for p in chord]
            token = chord[0]['token']
            # alphaTex 时值写在 beat 层级，跟在内容后面，加 . 前缀
            # 单音符: C4.4   和弦: (C4 E4 G4).4
            if len(names) == 1:
                bar_tokens.append(names[0] + '.' + token)
            else:
                bar_tokens.append('(' + ' '.join(names) + ').' + token)
            cursor += db

        # 小节末尾填充
        if cursor < bar_beats - 0.05:
            bar_tokens.append(_rest_tokens(bar_beats - cursor))

        lines.append(' '.join(t.strip() for t in bar_tokens) + ' |')

    return '\n'.join(lines) + '\n'


def _rest_tokens(gap_beats, tolerance=0.12):
    """把 gap_beats 拆成若干个休止符 token 串"""
    out = []
    remaining = gap_beats
    for valid, token in _VALID_BEATS:
        while remaining >= valid - tolerance:
            out.append('R' + token)
            remaining -= valid
            if len(out) > 4:
                break
        if len(out) > 4:
            break
    if remaining > 0.01 and not out:
        out = ['R16']
    return ' '.join(out)
