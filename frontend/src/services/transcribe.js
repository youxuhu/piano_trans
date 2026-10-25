/**
 * 文件 → 乐谱数据。统一入口：根据文件类型决定走哪条路。
 *
 * 返回值二选一：
 *   { kind: 'score',   url: string }  —— 通用二进制（MusicXML / Guitar Pro）→ 调 viewer.loadScore(url)
 *   { kind: 'alphatex', text: string } —— 纯文本 → 调 viewer.loadAlphaTex(text)
 *
 * 三条路径：
 *  1. 音频文件（mp3/wav/m4a/flac/aac/ogg/webm）—— POST 后端 /api/transcribe，
 *     后端内部完成"音频 → piano_transcription_inference → MIDI → music21 → MusicXML"，
 *     返回 MusicXML 二进制；前端转 blob URL 返回。
 *  2. 二进制乐谱文件（.musicxml / .xml / .gp / .gp5 / .gpx / .cap）—— 直接 blob URL
 *  3. 文本乐谱（.alphatex / .txt）—— FileReader 读文本
 *
 * 注：不提供 .mid 直接加载——alphaTab 只导出 MIDI，不导入 MIDI。
 */

const BACKEND = '/api'

const AUDIO_EXTS = /\.(mp3|wav|m4a|ogg|flac|aac|webm)$/i
const SCORE_EXTS = /\.(musicxml|xml|gp|gp3|gp4|gp5|gpx|cap)$/i

/**
 * @param {File} file
 * @returns {Promise<{kind: 'score'|'alphatex', url?: string, text?: string}>}
 */
export function transcribe(file) {
  return new Promise((resolve, reject) => {
    if (!file) return reject(new Error('未选择文件'))
    const name = (file.name || '').toLowerCase()

    // ① 二进制乐谱文件：直接 blob URL
    if (SCORE_EXTS.test(name)) {
      resolve({ kind: 'score', url: URL.createObjectURL(file) })
      return
    }

    // ② 文本乐谱
    if (name.endsWith('.alphatex') || name.endsWith('.txt')) {
      const reader = new FileReader()
      reader.onerror = () => reject(new Error('读取文本失败'))
      reader.onload = () => resolve({ kind: 'alphatex', text: reader.result })
      reader.readAsText(file)
      return
    }

    // ③ 音频 → 后端转 MusicXML
    if (AUDIO_EXTS.test(name)) {
      const fd = new FormData()
      fd.append('audio', file, file.name)

      fetch(`${BACKEND}/transcribe`, {
        method: 'POST',
        body: fd,
      }).then(async resp => {
        if (!resp.ok) {
          let detail = `HTTP ${resp.status}`
          try { const j = await resp.json(); if (j?.detail) detail = String(j.detail) } catch { /* ignore */ }
          throw new Error('后端转谱失败: ' + detail)
        }
        const blob = await resp.blob()
        resolve({ kind: 'score', url: URL.createObjectURL(blob) })
      }).catch(err => {
        reject(new Error(err?.message || '请求后端失败（后端是否已启动？）'))
      })
      return
    }

    reject(new Error('暂不支持此文件类型：' + (file.name || '(无)')))
  })
}
