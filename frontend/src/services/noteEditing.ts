import type { EditorNote } from './transcribe.ts'

export interface NoteSelection {
  pitch: number
  time: number
  hand: 'right' | 'left'
}
export function findSelectedNote(
  notes: EditorNote[],
  selection: NoteSelection,
  tolerance: number,
): EditorNote | undefined {
  return notes
    .filter(
      (n) =>
        n.pitch === selection.pitch &&
        n.start <= selection.time + tolerance &&
        n.end >= selection.time - tolerance,
    )
    .sort(
      (a, b) =>
        Math.abs(a.start - selection.time) +
        (a.hand && a.hand !== selection.hand ? 2 : 0) -
        (Math.abs(b.start - selection.time) + (b.hand && b.hand !== selection.hand ? 2 : 0)),
    )[0]
}
export function pitchLabel(pitch: number): string {
  return `${['C', 'C♯', 'D', 'D♯', 'E', 'F', 'F♯', 'G', 'G♯', 'A', 'A♯', 'B'][pitch % 12]}${Math.floor(pitch / 12) - 1}`
}
