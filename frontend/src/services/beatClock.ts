export interface BeatSettings {
  bpm: number
  meter: string
  subdivisions: number
}
export function beatsPerBar(meter: string) {
  return meter === '6/8' ? 2 : Number(meter.split('/')[0]) || 4
}

/** A short look-ahead queue schedules sound on the audio clock; frames only draw the pendulum. */
export class BeatClock {
  private context: AudioContext | null = null
  private timer = 0
  private frame = 0
  private generation = 0
  private nodes = new Set<OscillatorNode>()
  private finish: ((completed: boolean) => void) | null = null

  constructor(private onFrame: (angle: number, beat: number) => void = () => {}) {}

  async start(settings: BeatSettings, bars?: number): Promise<boolean> {
    this.stop()
    const generation = this.generation
    this.context ??= new AudioContext()
    const ctx = this.context
    await ctx.resume()
    if (generation !== this.generation) return false
    const duration = 60 / settings.bpm
    const beats = beatsPerBar(settings.meter)
    const subdivisions =
      settings.meter === '6/8' && settings.subdivisions === 1 ? 3 : settings.subdivisions
    const step = duration / subdivisions
    const start = ctx.currentTime + 0.06
    const end = bars ? start + bars * beats * duration : Infinity
    let next = start,
      index = 0
    const schedule = () => {
      while (next < ctx.currentTime + 0.12 && next < end - 0.001) {
        const oscillator = ctx.createOscillator(),
          gain = ctx.createGain()
        oscillator.frequency.value =
          index % (beats * subdivisions) === 0 ? 1100 : index % subdivisions === 0 ? 760 : 540
        gain.gain.setValueAtTime(0.0001, next)
        gain.gain.exponentialRampToValueAtTime(
          index % subdivisions === 0 ? 0.16 : 0.065,
          next + 0.004,
        )
        gain.gain.exponentialRampToValueAtTime(0.0001, next + 0.05)
        oscillator.connect(gain)
        gain.connect(ctx.destination)
        this.nodes.add(oscillator)
        oscillator.onended = () => {
          this.nodes.delete(oscillator)
          oscillator.disconnect()
          gain.disconnect()
        }
        oscillator.start(next)
        oscillator.stop(next + 0.055)
        next += step
        index++
      }
    }
    schedule()
    this.timer = window.setInterval(schedule, 25)
    const draw = () => {
      if (generation !== this.generation) return
      const elapsed = ctx.currentTime - start
      if (ctx.currentTime >= end) {
        const finish = this.finish
        this.finish = null
        this.stop()
        finish?.(true)
        return
      }
      if (elapsed >= 0)
        this.onFrame(
          -23 * Math.cos((Math.PI * elapsed) / duration),
          (Math.floor(elapsed / duration) % beats) + 1,
        )
      this.frame = requestAnimationFrame(draw)
    }
    this.frame = requestAnimationFrame(draw)
    if (!bars) return true
    return new Promise((resolve) => {
      this.finish = resolve
    })
  }

  stop() {
    this.generation++
    clearInterval(this.timer)
    cancelAnimationFrame(this.frame)
    for (const node of this.nodes) {
      try {
        node.stop()
      } catch {}
    }
    this.nodes.clear()
    this.onFrame(18, 0)
    const finish = this.finish
    this.finish = null
    finish?.(false)
  }
  dispose() {
    this.stop()
    void this.context?.close()
    this.context = null
  }
}
