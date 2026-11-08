/** AlphaTab position events expose elapsed wall time; the UI represents score time. */
export function playerMillisecondsToScoreSeconds(
  playerMilliseconds: number,
  speed: number,
): number {
  if (!Number.isFinite(playerMilliseconds) || !Number.isFinite(speed) || speed <= 0) return 0
  return Math.max(0, (playerMilliseconds * speed) / 1000)
}

/** AlphaTab's timePosition setter expects wall time because its sequencer applies playbackSpeed. */
export function scoreSecondsToPlayerMilliseconds(scoreSeconds: number, speed: number): number {
  if (!Number.isFinite(scoreSeconds) || !Number.isFinite(speed) || speed <= 0) return 0
  return Math.max(0, (scoreSeconds * 1000) / speed)
}
