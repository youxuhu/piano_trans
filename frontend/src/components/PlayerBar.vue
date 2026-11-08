<script setup lang="ts">
import { computed, ref, onMounted, onBeforeUnmount } from 'vue'

interface Props {
  duration?: number
  current?: number
  playing?: boolean
  ready?: boolean
  speed?: number
  loop?: boolean
  pointA?: number | null
  pointB?: number | null
  rangeError?: string
  sourceMode?: 'score' | 'original'
  originalAvailable?: boolean
}
const props = withDefaults(defineProps<Props>(), {
  duration: 0,
  current: 0,
  playing: false,
  ready: false,
  speed: 1,
  loop: false,
  pointA: null,
  pointB: null,
  rangeError: '',
  sourceMode: 'score',
  originalAvailable: false,
})
const emit = defineEmits<{
  toggle: []
  seek: [seconds: number]
  speed: [rate: number]
  loop: [enabled: boolean]
  setA: []
  setB: []
  clearRange: []
  sourceChange: [source: 'score' | 'original']
}>()

const isDragging = ref(false)
const wideScreen = ref(window.matchMedia('(min-width:1101px)').matches)
const extrasOpen = ref(false)
const media = window.matchMedia('(min-width:1101px)')
function updateScreen() {
  wideScreen.value = media.matches
  if (!media.matches) extrasOpen.value = false
}
function onExtrasToggle(event: Event) {
  if (!wideScreen.value) extrasOpen.value = (event.target as HTMLDetailsElement).open
}
onMounted(() => media.addEventListener('change', updateScreen))
onBeforeUnmount(() => media.removeEventListener('change', updateScreen))
const dragValue = ref(0)
function toggleLoop() {
  emit('loop', !props.loop)
}

// 可选倍速（市面伴奏/跟播软件常见的 0.5x–2.0x 档位）
const speedOptions = [0.5, 0.75, 1, 1.25, 1.5, 2]
function setSpeed(s: number): void {
  if (props.speed === s) return
  emit('speed', s)
}

function speedLabel(v: number): string {
  // 0.5 → 0.5x; 0.75 → 0.75x; 1 → 1x; 1.25 → 1.25x; etc.
  return `${v}x`
}

const clampedDuration = computed(() => Math.max(1, props.duration || 1))

function fmt(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds || 0))
  const mm = String(Math.floor(s / 60)).padStart(2, '0')
  const ss = String(s % 60).padStart(2, '0')
  return `${mm}:${ss}`
}

const label = computed(() => fmt(isDragging.value ? dragValue.value : props.current))
const percent = computed(() => {
  const v = isDragging.value ? dragValue.value : props.current
  return Math.min(100, (v / clampedDuration.value) * 100)
})

function onDragStart(v: number): void {
  isDragging.value = true
  dragValue.value = v
}
function onDrag(v: number): void {
  dragValue.value = v
}
function onDragEnd(v: number): void {
  isDragging.value = false
  emit('seek', v)
}
function onSliderInput(event: Event): void {
  if (event.target instanceof HTMLInputElement) onDragStart(Number(event.target.value))
}
function onSliderChange(event: Event): void {
  if (event.target instanceof HTMLInputElement) onDragEnd(Number(event.target.value))
}
</script>

<template>
  <div class="playerbar">
    <!-- 播放 / 循环按钮组 -->
    <div class="btn-row">
      <div class="source-switch" role="group" aria-label="播放音源">
        <button
          class="source-option"
          :class="{ on: sourceMode === 'score' }"
          :aria-pressed="sourceMode === 'score'"
          @click="emit('sourceChange', 'score')"
        >
          乐谱
        </button>
        <button
          class="source-option"
          :class="{ on: sourceMode === 'original' }"
          :disabled="!originalAvailable"
          :aria-pressed="sourceMode === 'original'"
          @click="emit('sourceChange', 'original')"
        >
          原音
        </button>
      </div>
      <button
        class="tp-btn main"
        :disabled="!ready"
        :title="playing ? '暂停' : '播放'"
        @click="emit('toggle')"
      >
        <span class="glyph">{{ playing ? '❚❚' : '▶' }}</span>
      </button>

      <button
        class="tp-btn loop"
        :disabled="!ready"
        :class="{ on: props.loop }"
        :title="props.loop ? '关闭循环' : '开启循环'"
        @click="toggleLoop"
      >
        <span class="glyph-loop">⟲</span>
      </button>
    </div>

    <div class="time-row">
      <span class="t-label">{{ label }}</span>
      <span class="t-total">/ {{ fmt(duration) }}</span>
    </div>

    <div class="slider-wrap">
      <div class="track" :style="{ '--pct': percent + '%' }">
        <div class="track-fill" />
        <input
          type="range"
          class="seek"
          aria-label="播放进度"
          :disabled="!ready"
          :min="0"
          :max="clampedDuration"
          :step="0.1"
          :value="isDragging ? dragValue : current"
          @input="onSliderInput"
          @change="onSliderChange"
        />
      </div>
    </div>

    <details class="extra-controls" :open="wideScreen || extrasOpen" @toggle="onExtrasToggle">
      <summary>更多</summary>
      <div class="extra-content">
        <!-- 倍速选择 -->
        <div class="speed-wrap">
          <button
            v-for="s in speedOptions"
            :key="s"
            class="chip"
            :disabled="!ready"
            :class="{ on: props.speed === s }"
            @click="setSpeed(s)"
          >
            {{ speedLabel(s) }}
          </button>
        </div>

        <div class="ab-row">
          <span class="ab-point" :class="{ marked: props.pointA != null }"
            >A {{ props.pointA == null ? '—' : fmt(props.pointA) }}</span
          >
          <span class="ab-point" :class="{ marked: props.pointB != null }"
            >B {{ props.pointB == null ? '—' : fmt(props.pointB) }}</span
          >
          <button class="ab-button" :disabled="!ready" @click="emit('setA')">设 A</button>
          <button
            class="ab-button"
            :disabled="!ready || props.pointA == null"
            @click="emit('setB')"
          >
            设 B
          </button>
          <button
            class="ab-button clear"
            :disabled="props.pointA == null && props.pointB == null"
            @click="emit('clearRange')"
          >
            清除
          </button>
          <span v-if="props.rangeError" class="ab-error">{{ props.rangeError }}</span>
        </div>
      </div>
    </details>

    <div class="hint">点击播放，光标随音符跟播 · 音源就绪后即刻发声</div>
  </div>
</template>

<style scoped>
.playerbar {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  width: 100%;
}
.extra-controls {
  display: block;
}
.extra-content {
  display: flex;
  align-items: center;
  gap: 14px;
}
.extra-controls summary {
  display: none;
  cursor: pointer;
  color: var(--ink-soft);
  padding: 7px;
  border: 1px solid #dce8e4;
  border-radius: 8px;
  font-size: 12px;
}
@media (max-width: 1100px) {
  .extra-controls {
    display: block;
    position: relative;
  }
  .extra-controls summary {
    display: block;
    list-style: none;
  }
  .extra-controls .extra-content {
    display: none;
  }
  .extra-controls[open] .extra-content {
    display: flex;
    position: absolute;
    z-index: 10;
    right: 0;
    bottom: 42px;
    width: min(320px, 80vw);
    flex-direction: column;
    align-items: stretch;
    gap: 14px;
    padding: 16px;
    background: #fff;
    border: 1px solid #dce8e4;
    border-radius: 12px;
    box-shadow: 0 8px 30px #24374720;
  }
  .extra-content .speed-wrap,
  .extra-content .ab-row {
    display: flex;
    flex-wrap: wrap;
    justify-content: flex-start;
  }
}
.tp-btn {
  border: 0;
  cursor: pointer;
  display: grid;
  place-items: center;
  transition:
    transform 0.15s,
    background 0.2s;
}
.btn-row {
  display: flex;
  align-items: center;
  gap: 14px;
}
.source-switch {
  display: inline-flex;
  padding: 3px;
  border: 1px solid var(--wood-200);
  border-radius: 9px;
  background: var(--wood-50);
}
.source-option {
  padding: 6px 9px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--ink-soft);
  cursor: pointer;
  font-size: 11px;
}
.source-option.on {
  background: #fff;
  color: var(--pine-700);
  box-shadow: 0 1px 4px #24374718;
}
.source-option:disabled {
  color: var(--ink-faint);
  cursor: not-allowed;
  opacity: 0.55;
}
.tp-btn.main {
  width: 64px;
  height: 64px;
  border-radius: 50%;
  background: var(--pine-600);
  color: #fff;
  font-size: 20px;
  box-shadow: 0 10px 20px -8px rgba(94, 122, 90, 0.6);
}
.tp-btn.main:hover:not(:disabled) {
  background: var(--pine-700);
  transform: scale(1.05);
}
.tp-btn.loop {
  width: 42px;
  height: 42px;
  border-radius: 50%;
  background: var(--paper);
  color: var(--ink-soft);
  border: 1px solid var(--wood-200);
  font-size: 20px;
}
.tp-btn.loop:hover {
  border-color: var(--pine-600);
  color: var(--pine-700);
  transform: scale(1.06);
}
.tp-btn.loop.on {
  background: linear-gradient(135deg, var(--pine-600), var(--pine-700));
  color: #fff;
  border-color: var(--pine-700);
}
.tp-btn:disabled {
  background: #c7c4bb;
  cursor: not-allowed;
  box-shadow: none;
}
.glyph {
  margin-left: 2px;
}
.time-row {
  display: flex;
  align-items: baseline;
  gap: 6px;
  font-family: var(--fontMono, ui-monospace, monospace);
}
.t-label {
  font-size: 22px;
  font-weight: 700;
  color: var(--ink);
}
.t-total {
  font-size: 13px;
  color: var(--ink-faint);
}

.slider-wrap {
  width: 100%;
}
.track {
  position: relative;
  height: 6px;
  border-radius: 4px;
  background: var(--wood-50);
}
.track-fill {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: var(--pct, 0%);
  background: linear-gradient(90deg, var(--gold), var(--pine-600));
  border-radius: 4px;
}
.seek {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  margin: 0;
  padding: 0;
  cursor: pointer;
  opacity: 0;
}
.hint {
  font-size: 12px;
  color: var(--ink-faint);
  text-align: center;
  line-height: 1.5;
}
.hint.off {
  opacity: 0.6;
}

/* 倍速档位 chips */
.speed-wrap {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  justify-content: center;
}
.ab-row {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
  justify-content: center;
}
.ab-point {
  font:
    11px ui-monospace,
    monospace;
  color: var(--ink-faint);
  padding: 4px 5px;
}
.ab-point.marked {
  color: var(--pine-700);
  font-weight: 700;
}
.ab-button {
  border: 1px solid var(--wood-200);
  border-radius: 7px;
  background: var(--paper);
  color: var(--ink-soft);
  font-size: 11px;
  padding: 5px 7px;
  cursor: pointer;
}
.ab-button:hover:not(:disabled) {
  border-color: var(--pine-600);
  color: var(--pine-700);
}
.ab-button:disabled {
  opacity: 0.42;
  cursor: not-allowed;
}
.ab-button.clear {
  color: var(--ink-faint);
}
.ab-error {
  flex-basis: 100%;
  text-align: center;
  color: #b75b56;
  font-size: 10px;
}
.chip {
  min-width: 42px;
  padding: 5px 8px;
  border-radius: 999px;
  border: 1px solid var(--wood-200);
  background: var(--paper);
  color: var(--ink-soft);
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  font-family: var(--fontMono, ui-monospace, monospace);
  transition: all 0.15s;
}
.chip:hover {
  border-color: var(--pine-600);
  color: var(--pine-700);
}
.chip.on {
  background: linear-gradient(135deg, var(--pine-600), var(--pine-700));
  border-color: var(--pine-700);
  color: #fff;
  box-shadow: 0 6px 14px -6px rgba(94, 122, 90, 0.6);
}
</style>
