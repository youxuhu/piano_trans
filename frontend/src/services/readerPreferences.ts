export interface ReaderPreferences {
  bar: number
  scale: number
  metroCollapsed: boolean
}
const PREFIX = 'lingpu.reader.'
export function readPreferences(id: string): ReaderPreferences {
  try {
    const saved = JSON.parse(localStorage.getItem(PREFIX + id) || '{}')
    return {
      bar: Number.isInteger(saved.bar) && saved.bar >= 0 ? saved.bar : 0,
      scale: Number.isFinite(saved.scale) ? Math.max(0.5, Math.min(2, saved.scale)) : 0.9,
      metroCollapsed: saved.metroCollapsed === true,
    }
  } catch {
    return { bar: 0, scale: 0.9, metroCollapsed: false }
  }
}
export function savePreferences(id: string, value: ReaderPreferences) {
  localStorage.setItem(PREFIX + id, JSON.stringify(value))
}
