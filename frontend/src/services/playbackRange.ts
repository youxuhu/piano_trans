export interface PlaybackTickRange {
  startTick: number
  endTick: number
}

export function createPlaybackRange(startTick: number, endTick: number): PlaybackTickRange | null {
  if (
    !Number.isFinite(startTick) ||
    !Number.isFinite(endTick) ||
    startTick < 0 ||
    endTick <= startTick
  )
    return null
  return { startTick, endTick }
}
