// 示例乐谱：MusicXML（从 backend/output/real_piano.mid 经 music21 转出，放在 public/）
export const sampleMidiUrl = '/real_piano.musicxml'

// 历史 AlphaTex 草稿（和弦语法曾导致 alphaTab 1.4.0 解析失败，暂保留备查）
export const sampleSheet = `
\\title "ethereal-piano-dreams_36526"

\\clef treble
\\tempo 120
R16. (C5 A5 F3 A4).4. C4.2 F4.2 A4.4. C5.4 A5.2 C4.4 (G5 A4 C5).4 F4.8. C4.16. A4.32 |
`
