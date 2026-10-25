<script setup>
import { AlphaTabApi, LayoutMode, Settings } from '@coderline/alphatab'
import { importer } from '@coderline/alphatab'
import { onBeforeUnmount, onMounted, ref } from 'vue'

const props = defineProps({
  initialSheet: { type: String, default: '' },
  initialScale: { type: Number, default: 0.9 },
})

const emit = defineEmits(['on-stats', 'on-load-fail', 'on-time', 'on-play-state'])

const host = ref(null)
let api = null
let lastStats = null
let rafId = null            // 轮询当前播放位置的 rAF
let currentSpeed = 1        // 当前倍速，用于把缩放后的 endTime 还原成真实曲长

/* —— 播放位置每帧轮询 alphaTab 合成器的 currentPosition ——
   getter 返回的是合成器真实毫秒位置，与乐谱光标、循环、倍速、seek 同一来源，
   不依赖可能未触发的位置事件，保证进度条/计时始终对齐。 */
function pollPosition() {
  try {
    const pos = api?.player?.currentPosition
    if (pos && typeof pos.currentTime === 'number') {
      // alphaTab 的 currentTime 已经除以倍速（getter = _currentTime / playbackSpeed），
      // 它反映的是真实墙钟物理秒。乘回倍速后，显示值 = 曲目内部位置：
      // 1x 显示 0,1,2...  2x 显示 0,2,4...（每秒涨两秒）  0.5x 显示 0,0.5,1...
      const sec = Math.max(0, Math.round((pos.currentTime * currentSpeed) / 10) / 100)
      emit('on-time', sec)
    }
    // 同理：endTime 也已除以倍速，乘回倍速即恒定真实曲长
    if (pos && typeof pos.endTime === 'number' && pos.endTime > 0) {
      const realMs = pos.endTime * currentSpeed
      if (!lastStats || lastStats.durationMs !== realMs) {
        lastStats = { ...lastStats, durationMs: realMs }
        emit('on-stats', lastStats)
      }
    }
  } catch { /* 忽略瞬时错误 */ }
  rafId = requestAnimationFrame(pollPosition)
}

function applyScale(s) {
  if (!api) return
  api.settings.display.scale = s
  api.updateSettings() // 让 alphaTab 应用 scale 改动
  api.render()
}

function zoomIn() {
  if (!api) return
  applyScale(Math.min(api.settings.display.scale + 0.1, 2))
}

function zoomOut() {
  if (!api) return
  applyScale(Math.max(api.settings.display.scale - 0.1, 0.5))
}

function buildSettings() {
  const s = new Settings()
  // Vite 插件把字体/音源复制到站点根目录的 font/ 与 soundfont/
  s.core.fontDirectory = '/font/'
  // 显式指定发声音源（避免 dev 模式下插件默认路径未注入导致音源不被加载）
  s.player.soundFont = '/soundfont/sonivox.sf2'
  s.player.enablePlayer = true
  s.display.scale = props.initialScale
  // Page 布局：根据容器宽度自动把多小节排成多行（默认一行横向铺开，换成 Page 以自动换行）
  s.display.layoutMode = LayoutMode.Page
  s.player.enableCursor = true
  s.player.scrollMode = 1 // ScrollMode.Continuous：光标随播放平滑滚动
  return s
}

/* —— 加载方式：AlphaTex 文本 或 乐谱文件 URL（MusicXML / Guitar Pro） —— */
function loadAlphaTex(src) {
  if (!api) return
  try {
    const score = importer.ScoreLoader.loadAlphaTex(src)
    api.renderScore(score)
  } catch (e) {
    emit('on-load-fail', 'AlphaTex 解析失败：' + String(e))
  }
}

/* loadScore 是 MusicXML / Guitar Pro 等二进制格式的统一入口：
   内部用 loadScoreFromBytes，alphaTab 会自动探测格式。
   URL 可以是 http(s) 地址或 URL.createObjectURL 生成的 blob URL。 */
async function loadScore(url) {
  if (!api) return
  try {
    const resp = await fetch(url)
    if (!resp.ok) throw new Error('HTTP ' + resp.status)
    const buf = new Uint8Array(await resp.arrayBuffer())
    const score = importer.ScoreLoader.loadScoreFromBytes(buf, api.settings)
    api.renderScore(score)
  } catch (e) {
    emit('on-load-fail', '乐谱加载失败：' + String(e))
  }
}

/* 兼容旧命名：loadMidi 其实一直不支持 .mid，已改为通用的 loadScore。
   此处保留别名，避免外部调用方断。 */
const loadMidi = loadScore

/* —— 跟播播放控制（供 PlayerBar 调用） —— */
function isReady() {
  return !!api // 按钮始终可点；音源未就绪时 alphaTab 会自行缓冲
}
function setLoop(loop) {
  if (!api) return
  try {
    api.player.isLooping = loop
  } catch { /* 忽略 */ }
}
function togglePlay() {
  if (!api) return
  try {
    api.togglePlay ? api.togglePlay() : api.playPause()
  } catch (e) {
    emit('on-load-fail', '播放失败：' + String(e))
  }
}
function stop() {
  if (!api) return
  api.stop()
  emit('on-time', 0)
}
function setSpeed(speed) {
  currentSpeed = speed
  if (!api) return
  try {
    api.playbackSpeed = speed
  } catch (e) {
    emit('on-load-fail', '倍速设置失败：' + String(e))
  }
}
function seek(seconds) {
  if (!api || api.player?.isReadyForPlayback === false) return
  try {
    // 直接设 alphaTab 播放时间；positionChanged 会随之上报 newTime，进度条/光标自动对齐
    api.player.timePosition = seconds
  } catch {
    emit('on-load-fail', '跳转失败：定位 API 不可用')
  }
}

function init() {
  api = new AlphaTabApi(host.value, buildSettings())
  // 统一错误上报（API 层事件用 error；soundFont* 事件在 synth 层，API 上不存在）
  api.error.on(e => emit('on-load-fail', '播放/渲染错误：' + (e?.message || e)))
  api.renderStarted.on(() => {})
  api.playerStateChanged.on(e => emit('on-play-state', e?.state))
  api.scoreLoaded.on(score => {
    // 加载时先按初始 BPM 与总 tick 估算；播放后以播放器报告的 endTime 为准
    let durationMs = 0
    try {
      if (score && Array.isArray(score.masterBars)) {
        const totalTicks = score.masterBars.reduce((sum, mb) => sum + (mb?.calculateDuration() || 0), 0)
        const quarterTicks = 480 // MidiUtils.QuarterTime
        const tempo = score.tempo || 120
        durationMs = (totalTicks / quarterTicks / tempo) * 60000
      }
    } catch {
      durationMs = 0
    }
    lastStats = {
      title: score?.title || '未命名曲目',
      tracks: score?.tracks?.length || 0,
      bars: score?.masterBars?.length || 0,
      durationMs,
    }
    emit('on-stats', lastStats)
  })
  // 默认加载示例乐谱（放在 public/ 下，Vite 直接通过根路径访问）
  // loadScoreFromBytes 会自动探测 MusicXML / Guitar Pro 格式
  if (props.initialSheet && !props.initialSheet.endsWith('.alphatex') && !props.initialSheet.endsWith('.txt')) {
    loadScore(props.initialSheet)
  } else if (props.initialSheet) {
    loadAlphaTex(props.initialSheet)
  }
  rafId = requestAnimationFrame(pollPosition)
}

onMounted(() => {
  // 等首帧布局稳定后再初始化，避免宽度为 0
  requestAnimationFrame(() => {
    requestAnimationFrame(init)
  })
})

onBeforeUnmount(() => {
  if (rafId) cancelAnimationFrame(rafId)
  api?.destroy()
  api = null
})

defineExpose({ zoomIn, zoomOut, loadScore, loadMidi, loadAlphaTex, togglePlay, stop, seek, isReady, setSpeed, setLoop })
</script>

<template>
  <div ref="host" class="at-host" />
</template>

<style scoped>
.at-host {
  width: 100%;
  max-width: 100%;
  min-width: 0;
  min-height: 280px;
  overflow-x: auto;  /* 已按 Page 布局换行，极窄时可横向滚动兜底 */
  overflow-y: hidden;
  padding: 8px 4px;
}
.at-host .at-viewport,
.at-host :deep(.alphaTabSurface canvas) {
  max-width: 100%;
}
</style>

<!-- alphaTab 动态注入的光标元素不在本组件模板树内，需用非 scoped 全局样式上色 -->
<style>
.at-cursor-bar {
  background: rgba(200, 164, 92, 0.32) !important;
  border-left: 2px solid rgba(94, 122, 90, 0.85) !important;
  z-index: 5;
}
.at-cursor-beat {
  background: rgba(200, 164, 92, 0.38) !important;
  z-index: 4;
}
</style>