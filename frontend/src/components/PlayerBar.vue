<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  duration: { type: Number, default: 0 }, // 秒
  current: { type: Number, default: 0 },  // 秒
  playing: { type: Boolean, default: false },
  ready: { type: Boolean, default: false },
})
const emit = defineEmits(['toggle', 'seek', 'speed', 'loop'])

const isDragging = ref(false)
const dragValue = ref(0)
const loop = ref(false)

function toggleLoop() {
  loop.value = !loop.value
  emit('loop', loop.value)
}

// 可选倍速（市面伴奏/跟播软件常见的 0.5x–2.0x 档位）
const speedOptions = [0.5, 0.75, 1, 1.25, 1.5, 2]
const speed = ref(1)

function setSpeed(s) {
  if (speed.value === s) return
  speed.value = s
  emit('speed', s)
}

function speedLabel(v) {
  // 0.5 → 0.5x; 0.75 → 0.75x; 1 → 1x; 1.25 → 1.25x; etc.
  return `${v}x`
}

const clampedDuration = computed(() => Math.max(1, props.duration || 1))

function fmt(seconds) {
  const s = Math.max(0, Math.floor(seconds || 0))
  const mm = String(Math.floor(s / 60)).padStart(2, '0')
  const ss = String(s % 60).padStart(2, '0')
  return `${mm}:${ss}`
}

const label = computed(() =>
  fmt(isDragging.value ? dragValue.value : props.current)
)
const percent = computed(() => {
  const v = isDragging.value ? dragValue.value : props.current
  return Math.min(100, (v / clampedDuration.value) * 100)
})

function onDragStart(v) {
  isDragging.value = true
  dragValue.value = v
}
function onDrag(v) {
  dragValue.value = v
}
function onDragEnd(v) {
  isDragging.value = false
  emit('seek', v)
}
</script>

<template>
  <div class="playerbar">
    <!-- 播放 / 循环按钮组 -->
    <div class="btn-row">
      <button
        class="tp-btn main"
        :title="playing ? '暂停' : '播放'"
        @click="emit('toggle')"
      >
        <span class="glyph">{{ playing ? '❚❚' : '▶' }}</span>
      </button>

      <button
        class="tp-btn loop"
        :class="{ on: loop }"
        :title="loop ? '关闭循环' : '开启循环'"
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
          :min="0"
          :max="clampedDuration"
          :step="0.1"
          :value="isDragging ? dragValue : current"
          @input="onDrag(parseFloat($event.target.value))"
          @change="onDragEnd(parseFloat($event.target.value))"
        />
      </div>
    </div>

    <!-- 倍速选择 -->
    <div class="speed-wrap">
      <button
        v-for="s in speedOptions"
        :key="s"
        class="chip"
        :class="{ on: speed === s }"
        @click="setSpeed(s)"
      >
        {{ speedLabel(s) }}
      </button>
    </div>

    <div class="hint">点击播放，光标随音符跟播 · 音源就绪后即刻发声</div>
  </div>
</template>

<style scoped>
.playerbar {
  display: flex; flex-direction: column; align-items: center; gap: 12px; width: 100%;
}
.tp-btn { border: 0; cursor: pointer; display: grid; place-items: center; transition: transform .15s, background .2s; }
.btn-row { display: flex; align-items: center; gap: 14px; }
.tp-btn.main {
  width: 64px; height: 64px; border-radius: 50%;
  background: var(--pine-600); color: #fff; font-size: 20px;
  box-shadow: 0 10px 20px -8px rgba(94, 122, 90, 0.6);
}
.tp-btn.main:hover:not(:disabled) { background: var(--pine-700); transform: scale(1.05); }
.tp-btn.loop {
  width: 42px; height: 42px; border-radius: 50%;
  background: var(--paper); color: var(--ink-soft);
  border: 1px solid var(--wood-200); font-size: 20px;
}
.tp-btn.loop:hover { border-color: var(--pine-600); color: var(--pine-700); transform: scale(1.06); }
.tp-btn.loop.on {
  background: linear-gradient(135deg, var(--gold), #c9a55e); color: #fff;
  border-color: #b89351;
}
.tp-btn:disabled { background: #c7c4bb; cursor: not-allowed; box-shadow: none; }
.glyph { margin-left: 2px; }
.time-row { display: flex; align-items: baseline; gap: 6px; font-family: var(--fontMono, ui-monospace, monospace); }
.t-label { font-size: 22px; font-weight: 700; color: var(--ink); }
.t-total { font-size: 13px; color: var(--ink-faint); }

.slider-wrap { width: 100%; }
.track {
  position: relative; height: 6px; border-radius: 4px;
  background: var(--wood-50);
}
.track-fill {
  position: absolute; left: 0; top: 0; bottom: 0; width: var(--pct, 0%);
  background: linear-gradient(90deg, var(--gold), var(--pine-600));
  border-radius: 4px;
}
.seek {
  position: absolute; inset: 0; width: 100%; height: 100%;
  margin: 0; padding: 0; cursor: pointer; opacity: 0;
}
.hint { font-size: 12px; color: var(--ink-faint); text-align: center; line-height: 1.5; }
.hint.off { opacity: 0.6; }

/* 倍速档位 chips */
.speed-wrap { display: flex; gap: 4px; flex-wrap: wrap; justify-content: center; }
.chip {
  min-width: 42px; padding: 5px 8px; border-radius: 999px;
  border: 1px solid var(--wood-200); background: var(--paper);
  color: var(--ink-soft); font-size: 12.5px; font-weight: 600;
  cursor: pointer; font-family: var(--fontMono, ui-monospace, monospace);
  transition: all .15s;
}
.chip:hover { border-color: var(--pine-600); color: var(--pine-700); }
.chip.on {
  background: linear-gradient(135deg, var(--pine-600), var(--pine-700));
  border-color: var(--pine-700); color: #fff;
  box-shadow: 0 6px 14px -6px rgba(94,122,90,0.6);
}
</style>