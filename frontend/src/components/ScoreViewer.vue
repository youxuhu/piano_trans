<script setup lang="ts">
import {
  AlphaTabApi,
  LayoutMode,
  ScrollMode,
  Settings,
  SystemsLayoutMode,
} from '@coderline/alphatab'
import { importer } from '@coderline/alphatab'
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { createPlaybackRange } from '../services/playbackRange'
import { normalizeScoreDisplayTitle, paginateScoreSystems } from '../services/scorePagination'
import {
  playerMillisecondsToScoreSeconds,
  scoreSecondsToPlayerMilliseconds,
} from '../services/playerTime'

interface ScoreStats {
  title: string
  tracks: number
  bars: number
  durationMs: number
}
const props = withDefaults(
  defineProps<{
    initialSheet?: string
    initialScale?: number
    displayTitle?: string
    editMode?: boolean
  }>(),
  {
    initialSheet: '',
    initialScale: 0.9,
  },
)
const emit = defineEmits<{
  'on-stats': [stats: ScoreStats]
  'on-load-fail': [message: string]
  'on-time': [seconds: number]
  'on-play-state': [state: number]
  'on-ready': [ready: boolean]
  'on-cleared': []
  'on-score-loading': []
  'on-api-ready': [ready: boolean]
  'on-page-change': [payload: { page: number; total: number }]
  'on-reading-change': [payload: { bar: number; scale: number }]
  'on-rendered': []
  'on-note-select': [payload: { pitch: number; time: number; hand: 'right' | 'left' }]
}>()

const host = ref<HTMLElement | null>(null)
const scrollViewport = ref<HTMLElement | null>(null)
const paperHeading = ref<HTMLElement | null>(null)
const paperTitle = ref('')
const selectedMarker = ref<{ left: number; top: number; width: number; height: number } | null>(
  null,
)
const paperSubtitle = ref('')
const pageTitleSpace = ref(0)
let api: AlphaTabApi | null = null
let lastStats: ScoreStats | null = null
let disposed = false
let loadGeneration = 0
let followingOriginalAudio = false
let lastOriginalFollowY: number | null = null
let followUpdateGeneration = 0
let pages: ReturnType<typeof paginateScoreSystems> = []
let pageIndex = 0
let resizeObserver: ResizeObserver | null = null
let customDisplayTitle = props.displayTitle?.trim() || ''
let apiWaiters: Array<(instance: AlphaTabApi | null) => void> = []
let lastCursorPage: number | null = null
let manualPageHold = false
let pendingForcePageFollow = false
let readingBar = 0
let renderPending = false
let followEnabled = false

function measurePaperHeading() {
  pageTitleSpace.value =
    !props.editMode && paperTitle.value && paperHeading.value
      ? Math.ceil(paperHeading.value.getBoundingClientRect().height)
      : 0
}

function waitForApi(): Promise<AlphaTabApi | null> {
  if (api) return Promise.resolve(api)
  return new Promise((resolve) => apiWaiters.push(resolve))
}

function resolveApiWaiters(instance: AlphaTabApi | null) {
  const waiting = apiWaiters
  apiWaiters = []
  for (const resolve of waiting) resolve(instance)
}

function applyScale(s: number) {
  if (!api) return
  renderPending = true
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
  // Page navigation owns score-area clicks; seeking and A/B selection are provided by PlayerBar.
  s.player.enableUserInteraction = false
  s.display.scale = props.initialScale
  // Page 布局：根据容器宽度自动把多小节排成多行（默认一行横向铺开，换成 Page 以自动换行）
  s.display.layoutMode = LayoutMode.Page
  s.display.systemsLayoutMode = SystemsLayoutMode.Automatic
  s.display.barsPerRow = -1
  s.core.enableLazyLoading = false
  s.core.includeNoteBounds = true
  s.player.enableCursor = true
  // The viewport is a clipped paper page; alphaTab must not scroll it while
  // the component moves between pages from cursor position updates.
  s.player.scrollMode = ScrollMode.Off
  if (scrollViewport.value) s.player.scrollElement = scrollViewport.value
  s.player.scrollOffsetY = -24
  return s
}

/* —— 加载方式：AlphaTex 文本 或 乐谱文件 URL（MusicXML / Guitar Pro） —— */
function loadAlphaTex(src: string) {
  if (!api) return
  paperTitle.value = ''
  paperSubtitle.value = ''
  pageTitleSpace.value = 0
  loadGeneration++
  resetPlaybackForScoreChange()
  try {
    const score = importer.ScoreLoader.loadAlphaTex(src)
    api.renderScore(
      score,
      score.tracks.map((_track, index) => index),
    )
  } catch (e) {
    emit('on-load-fail', 'AlphaTex 解析失败：' + String(e))
  }
}

/* loadScore 是 MusicXML / Guitar Pro 等二进制格式的统一入口：
   内部用 loadScoreFromBytes，alphaTab 会自动探测格式。
   URL 可以是 http(s) 地址或 URL.createObjectURL 生成的 blob URL。 */
async function loadScore(
  url: string,
  title?: string,
  preferences?: { bar: number; scale: number },
): Promise<void> {
  const generation = ++loadGeneration
  customDisplayTitle = title?.trim() || props.displayTitle?.trim() || ''
  const targetApi = api ?? (await waitForApi())
  if (!targetApi || generation !== loadGeneration || disposed) return
  resetPlaybackForScoreChange()
  readingBar = preferences?.bar ?? 0
  targetApi.settings.display.scale = preferences?.scale ?? props.initialScale
  targetApi.updateSettings()
  renderPending = true
  try {
    const resp = await fetch(url)
    if (!resp.ok) throw new Error('HTTP ' + resp.status)
    const buf = new Uint8Array(await resp.arrayBuffer())
    if (generation !== loadGeneration || api !== targetApi || disposed) return
    const score = importer.ScoreLoader.loadScoreFromBytes(buf, targetApi.settings)
    const display = normalizeScoreDisplayTitle(customDisplayTitle || score.title, score.subTitle)
    paperTitle.value = display.title
    paperSubtitle.value = display.subtitle
    await nextTick()
    measurePaperHeading()
    // Render the long label in our wrapping paper heading; a single alphaTab
    // title line is clipped on portrait pages.
    score.title = ''
    score.subTitle = ''
    targetApi.renderScore(
      score,
      score.tracks.map((_track, index) => index),
    )
  } catch (e) {
    renderPending = false
    if (generation !== loadGeneration || api !== targetApi || disposed) return
    emit('on-load-fail', '乐谱加载失败：' + String(e))
  }
}

/* 兼容旧命名：loadMidi 其实一直不支持 .mid，已改为通用的 loadScore。
   此处保留别名，避免外部调用方断。 */
const loadMidi = loadScore

/* —— 跟播播放控制（供 PlayerBar 调用） —— */
function isReady() {
  return !!api?.isReadyForPlayback
}
function setLoop(loop: boolean) {
  if (!api) return
  try {
    api.isLooping = loop
  } catch {
    /* 忽略 */
  }
}
function currentTick(): number {
  return api?.tickPosition ?? 0
}
function setPlaybackRange(startTick: number, endTick: number): boolean {
  const range = createPlaybackRange(startTick, endTick)
  if (!api || !api.isReadyForPlayback || !range) return false
  api.playbackRange = range
  api.isLooping = true
  return true
}
function clearPlaybackRange(): void {
  if (!api) return
  api.playbackRange = null
  api.isLooping = false
}
function resetPlaybackForScoreChange(): void {
  if (!api) return
  lastStats = null
  lastCursorPage = null
  manualPageHold = false
  followEnabled = false
  pendingForcePageFollow = false
  followingOriginalAudio = false
  lastOriginalFollowY = null
  followUpdateGeneration++
  api.stop()
  api.timePosition = 0
  api.playbackRange = null
  api.playbackSpeed = 1
  api.isLooping = false
  emit('on-time', 0)
  emit('on-ready', false)
  emit('on-score-loading')
}
function followOriginalAudio(seconds: number, forceFollow = false) {
  if (!api?.isReadyForPlayback) return
  followEnabled = true
  followingOriginalAudio = true
  if (forceFollow) lastOriginalFollowY = null
  if (forceFollow) pendingForcePageFollow = true
  api.timePosition = scoreSecondsToPlayerMilliseconds(seconds, api.playbackSpeed)
}

function emitPage() {
  emit('on-page-change', { page: pages.length ? pageIndex + 1 : 0, total: pages.length })
}

function showPage(index: number, preserveAnchor = false) {
  selectedMarker.value = null
  pageIndex = Math.max(0, Math.min(Math.trunc(index), Math.max(0, pages.length - 1)))
  const page = pages[pageIndex]
  const viewport = scrollViewport.value
  const content = host.value
  const firstBar = page && api?.boundsLookup?.staffSystems[page.firstSystem]?.bars[0]?.index
  if (firstBar != null) {
    if (!preserveAnchor) readingBar = firstBar
    emit('on-reading-change', {
      bar: readingBar,
      scale: api?.settings.display.scale ?? props.initialScale,
    })
  }
  if (paperHeading.value)
    paperHeading.value.style.visibility = pageIndex === 0 ? 'visible' : 'hidden'
  if (!page || !viewport || !content) {
    content?.style.removeProperty('transform')
    content?.style.removeProperty('clip-path')
    content?.style.removeProperty('width')
    emitPage()
    return
  }
  const height = Math.max(1, viewport.clientHeight)
  const titleSpace = pageIndex === 0 ? pageTitleSpace.value : 0
  const pageHeight = Math.max(1, page.bottom - page.top + titleSpace)
  const scale = Math.min(1, height / pageHeight)
  content.style.transformOrigin = 'top left'
  content.style.transform = `scale(${scale}) translateY(${-page.top + titleSpace}px)`
  const hostHeight = content.offsetHeight
  content.style.clipPath = `inset(${page.top}px 0 ${Math.max(0, hostHeight - page.bottom)}px 0)`
  emitPage()
}

function previousPage() {
  manualPageHold = true
  showPage(pageIndex - 1)
}
function nextPage() {
  manualPageHold = true
  showPage(pageIndex + 1)
}

function pageForTick(tick: number): number {
  const score = api?.score
  const lookup = api?.boundsLookup
  if (!score || !lookup || !pages.length) return -1
  let startTick = 0
  let masterBarIndex = Math.max(0, score.masterBars.length - 1)
  for (let i = 0; i < score.masterBars.length; i++) {
    const endTick = startTick + (score.masterBars[i]?.calculateDuration() || 0)
    if (tick < endTick || i === score.masterBars.length - 1) {
      masterBarIndex = i
      break
    }
    startTick = endTick
  }
  const systemIndex = lookup.findMasterBarByIndex(masterBarIndex)?.staffSystemBounds?.index
  if (systemIndex == null) return -1
  return pages.findIndex((page) => page.firstSystem <= systemIndex && systemIndex < page.endSystem)
}

function syncPageToTick(tick: number, force = false) {
  const target = pageForTick(tick)
  if (target < 0) return
  if (force) {
    manualPageHold = false
    lastCursorPage = target
    showPage(target)
    return
  }
  if (lastCursorPage == null) {
    lastCursorPage = target
    if (!manualPageHold) showPage(target)
    return
  }
  if (target === lastCursorPage) return
  lastCursorPage = target
  if (manualPageHold) manualPageHold = false
  showPage(target)
}

function repaginate() {
  if (renderPending) return
  const systems = api?.boundsLookup?.staffSystems
  const viewport = scrollViewport.value
  if (!systems?.length || !viewport) {
    pages = []
    pageIndex = 0
    showPage(0)
    return
  }
  measurePaperHeading()
  pages = paginateScoreSystems(
    systems.map((system, index) => ({
      top: index === 0 ? 0 : system.realBounds.y,
      bottom: system.realBounds.y + system.realBounds.h,
    })),
    Math.max(1, viewport.clientHeight - 12),
    Math.max(1, viewport.clientHeight - 12 - pageTitleSpace.value),
  )
  const anchorSystem = api?.boundsLookup?.findMasterBarByIndex(readingBar)?.staffSystemBounds?.index
  const anchoredPage =
    anchorSystem == null
      ? -1
      : pages.findIndex((p) => p.firstSystem <= anchorSystem && anchorSystem < p.endSystem)
  const resolvedTarget = anchoredPage < 0 ? Math.min(pageIndex, pages.length - 1) : anchoredPage
  showPage(resolvedTarget, true)
}

function fitWidth() {
  applyScale(0.9)
}
function fitPage() {
  const page = pages[pageIndex]
  if (!api || !page || !scrollViewport.value) return
  const height = page.bottom - page.top + (pageIndex === 0 ? pageTitleSpace.value : 0)
  applyScale(
    Math.max(
      0.5,
      Math.min(
        2,
        (api.settings.display.scale * (scrollViewport.value.clientHeight - 20)) /
          Math.max(height, 1),
      ),
    ),
  )
}
function setHandVolumes(right: number, left: number) {
  const tracks = api?.score?.tracks
  if (!api || !tracks) return
  if (tracks[0]) api.changeTrackVolume([tracks[0]], right / 100)
  if (tracks[1]) api.changeTrackVolume([tracks[1]], left / 100)
}
function printScore() {
  if (!api?.score) return
  try {
    api.score.title = paperTitle.value
    api.print('210mm', { display: { scale: 1, barsPerRow: -1 } })
  } catch (e) {
    emit('on-load-fail', '无法打开打印预览：' + String(e))
  } finally {
    if (api?.score) api.score.title = ''
  }
}

let touchStart: { x: number; y: number } | null = null
let suppressClickUntil = 0

function onScoreTouchStart(event: TouchEvent) {
  const touch = event.touches.length === 1 ? event.touches[0] : null
  touchStart = touch ? { x: touch.clientX, y: touch.clientY } : null
}

function onScoreTouchEnd(event: TouchEvent) {
  const touch = event.changedTouches[0]
  if (!touchStart || !touch || event.touches.length) {
    touchStart = null
    return
  }
  const dx = touch.clientX - touchStart.x
  const dy = touch.clientY - touchStart.y
  touchStart = null
  if (Math.hypot(dx, dy) > 12) suppressClickUntil = Date.now() + 700
  if (Math.abs(dx) < 50 || Math.abs(dx) < Math.abs(dy) * 1.4) return
  if (dx < 0) nextPage()
  else previousPage()
}

function onScoreClick(event: MouseEvent) {
  if (Date.now() < suppressClickUntil) return
  const target = event.target
  if (
    !(target instanceof Element) ||
    !target.closest('.at-scroll-viewport, .at-host, svg, canvas, .at-viewport')
  )
    return
  if (target.closest('button, a, input, select, textarea, [role="button"]')) return
  if (props.editMode) {
    const content = host.value,
      viewport = scrollViewport.value,
      lookup = api?.boundsLookup
    if (!content || !viewport || !lookup || !api?.score) return
    const rect = content.getBoundingClientRect(),
      view = viewport.getBoundingClientRect()
    const scale = rect.width / Math.max(1, content.offsetWidth)
    const x = (event.clientX - rect.left) / scale,
      y = (event.clientY - rect.top) / scale
    const beat = lookup.getBeatAtPos(x, y)
    const note = beat && lookup.getNoteAtPos(beat, x, y)
    if (!note || !beat) return
    const bounds = lookup.findBeat(beat)?.notes?.find((n) => n.note === note)?.noteHeadBounds
    if (bounds)
      selectedMarker.value = {
        left: bounds.x * scale + rect.left - view.left - 5,
        top: bounds.y * scale + rect.top - view.top - 5,
        width: bounds.w * scale + 10,
        height: bounds.h * scale + 10,
      }
    emit('on-note-select', {
      pitch: note.realValue,
      time: ((beat.absolutePlaybackStart / 960) * 60) / (api.score.tempo || 120),
      hand: beat.voice.bar.staff.track.index === 0 ? 'right' : 'left',
    })
    return
  }
  const bounds = scrollViewport.value?.getBoundingClientRect()
  if (!bounds) return
  const x = event.clientX - bounds.left
  if (x < bounds.width / 2) previousPage()
  else nextPage()
}

function pause() {
  api?.pause()
}

function togglePlay() {
  followEnabled = true
  followingOriginalAudio = false
  if (!api) return
  try {
    api.playPause()
  } catch (e) {
    emit('on-load-fail', '播放失败：' + String(e))
  }
}
function stop() {
  if (!api) return
  followEnabled = false
  api.stop()
  emit('on-time', 0)
}
function clearScore() {
  if (!api || !host.value) return
  const oldApi = api
  loadGeneration++
  api = null
  lastStats = null
  pages = []
  pageIndex = 0
  lastCursorPage = null
  manualPageHold = false
  oldApi.stop()
  oldApi.destroy()
  host.value.replaceChildren()
  showPage(0)
  emit('on-ready', false)
  emit('on-api-ready', false)
  emit('on-cleared')
  init()
}
function setSpeed(speed: number) {
  if (!api) return
  try {
    api.playbackSpeed = speed
  } catch (e) {
    emit('on-load-fail', '倍速设置失败：' + String(e))
  }
}
function seek(seconds: number) {
  if (!api || !api.isReadyForPlayback) return
  try {
    followEnabled = true
    pendingForcePageFollow = true
    // 直接设 alphaTab 播放时间；positionChanged 会随之上报 newTime，进度条/光标自动对齐
    api.timePosition = scoreSecondsToPlayerMilliseconds(seconds, api.playbackSpeed)
  } catch {
    emit('on-load-fail', '跳转失败：定位 API 不可用')
  }
}

function init() {
  if (!host.value) return
  const instance = new AlphaTabApi(host.value, buildSettings())
  api = instance
  resolveApiWaiters(instance)
  emit('on-api-ready', true)
  // 统一错误上报（API 层事件用 error；soundFont* 事件在 synth 层，API 上不存在）
  instance.error.on((e) => {
    if (api === instance) emit('on-load-fail', '播放/渲染错误：' + (e?.message || e))
  })
  instance.playerReady.on(() => {
    if (api === instance) emit('on-ready', instance.isReadyForPlayback)
  })
  instance.soundFontLoaded.on(() => {
    if (api === instance) emit('on-ready', instance.isReadyForPlayback)
  })
  instance.midiLoaded.on(() => {
    if (api === instance) emit('on-ready', instance.isReadyForPlayback)
  })
  instance.playerPositionChanged.on((pos) => {
    if (api !== instance) return
    const forcePageFollow = pos.isSeek || pendingForcePageFollow
    pendingForcePageFollow = false
    if (followEnabled && !renderPending) syncPageToTick(pos.currentTick, forcePageFollow)
    if (followingOriginalAudio) {
      const generation = ++followUpdateGeneration
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          if (api === instance && followingOriginalAudio && generation === followUpdateGeneration) {
            syncPageToTick(pos.currentTick, forcePageFollow)
          }
        })
      })
    }
    const speed = instance.playbackSpeed
    emit('on-time', playerMillisecondsToScoreSeconds(pos.currentTime, speed))
    if (pos.endTime > 0 && lastStats) {
      lastStats = { ...lastStats, durationMs: pos.endTime * speed }
      emit('on-stats', lastStats)
    }
  })
  instance.playerStateChanged.on((e) => {
    if (api === instance) emit('on-play-state', e.state)
  })
  instance.scoreLoaded.on((score) => {
    if (api !== instance) return
    resetPlaybackForScoreChange()
    if (scrollViewport.value) scrollViewport.value.scrollTop = 0
    // 加载时先按初始 BPM 与总 tick 估算；播放后以播放器报告的 endTime 为准
    let durationMs = 0
    try {
      if (score && Array.isArray(score.masterBars)) {
        const totalTicks = score.masterBars.reduce(
          (sum, mb) => sum + (mb?.calculateDuration() || 0),
          0,
        )
        const quarterTicks = 960 // alphaTab MidiUtils.QuarterTime
        const tempo = score.tempo || 120
        durationMs = (totalTicks / quarterTicks / tempo) * 60000
      }
    } catch {
      durationMs = 0
    }
    lastStats = {
      title:
        paperTitle.value ||
        normalizeScoreDisplayTitle(customDisplayTitle || score?.title, score?.subTitle).title,
      tracks: score?.tracks?.length || 0,
      bars: score?.masterBars?.length || 0,
      durationMs,
    }
    emit('on-stats', lastStats)
  })
  instance.postRenderFinished.on(() => {
    if (api === instance) {
      renderPending = false
      requestAnimationFrame(() => {
        repaginate()
        emit('on-rendered')
      })
    }
  })
  // 默认加载示例乐谱（放在 public/ 下，Vite 直接通过根路径访问）
  // loadScoreFromBytes 会自动探测 MusicXML / Guitar Pro 格式
  if (
    props.initialSheet &&
    !props.initialSheet.endsWith('.alphatex') &&
    !props.initialSheet.endsWith('.txt')
  ) {
    void loadScore(props.initialSheet)
  } else if (props.initialSheet) {
    loadAlphaTex(props.initialSheet)
  }
}

onMounted(() => {
  // 等首帧布局稳定后再初始化，避免宽度为 0
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      if (!disposed) init()
    })
  })
  resizeObserver = new ResizeObserver(() => requestAnimationFrame(repaginate))
  if (scrollViewport.value) resizeObserver.observe(scrollViewport.value)
})

onBeforeUnmount(() => {
  disposed = true
  resizeObserver?.disconnect()
  emit('on-ready', false)
  emit('on-api-ready', false)
  api?.destroy()
  api = null
  resolveApiWaiters(null)
})

watch(() => props.editMode, async () => { await nextTick(); measurePaperHeading(); repaginate() })

defineExpose({
  zoomIn,
  zoomOut,
  loadScore,
  loadMidi,
  loadAlphaTex,
  togglePlay,
  pause,
  followOriginalAudio,
  stop,
  seek,
  isReady,
  setSpeed,
  setLoop,
  currentTick,
  setPlaybackRange,
  clearPlaybackRange,
  clearScore,
  previousPage,
  nextPage,
  fitWidth,
  fitPage,
  setHandVolumes,
  printScore,
})
</script>

<template>
  <div
    ref="scrollViewport"
    class="at-scroll-viewport"
    @click="onScoreClick"
    @touchstart.passive="onScoreTouchStart"
    @touchend.passive="onScoreTouchEnd"
    @touchcancel="touchStart = null"
  >
    <div v-if="paperTitle && !editMode" ref="paperHeading" class="paper-heading">
      <div class="paper-title">{{ paperTitle }}</div>
      <div v-if="paperSubtitle" class="paper-subtitle">{{ paperSubtitle }}</div>
    </div>
    <div ref="host" class="at-host" />
    <div
      v-if="editMode && selectedMarker"
      class="selected-note"
      :style="{
        left: selectedMarker.left + 'px',
        top: selectedMarker.top + 'px',
        width: selectedMarker.width + 'px',
        height: selectedMarker.height + 'px',
      }"
    />
  </div>
</template>

<style scoped>
.at-scroll-viewport {
  width: 100%;
  max-width: 100%;
  min-width: 0;
  min-height: 0;
  height: 100%;
  flex: 1 1 auto;
  overflow: hidden;
  touch-action: pan-y pinch-zoom;
  position: relative;
  scrollbar-width: none;
  background: #fff;
  border: 1px solid #dce3e6;
  box-shadow: 0 3px 14px rgba(34, 52, 62, 0.08);
}
.selected-note {
  position: absolute;
  z-index: 4;
  border: 2px solid #b78545;
  border-radius: 8px;
  background: #e7c28b33;
  pointer-events: none;
}
.at-host {
  width: 100%;
  max-width: 100%;
  min-width: 0;
}
.paper-heading {
  position: absolute;
  z-index: 3;
  inset: 0 0 auto;
  box-sizing: border-box;
  height: auto;
  padding: 10px 16px 12px;
  text-align: center;
  pointer-events: none;
}
.paper-title {
  color: #202326;
  font-family: Georgia, 'Noto Serif', serif;
  font-size: clamp(18px, 2vw, 28px);
  font-weight: 600;
  line-height: 1.3;
  overflow-wrap: anywhere;
}
.paper-subtitle {
  margin-top: 4px;
  color: #444;
  font-family: Georgia, 'Noto Serif', serif;
  font-size: clamp(8px, 1vw, 14px);
  line-height: 1.3;
  overflow-wrap: anywhere;
}
.at-host .at-viewport,
.at-host :deep(.alphaTabSurface canvas) {
  max-width: 100%;
}
</style>

<!-- alphaTab 动态注入的光标元素不在本组件模板树内，需用非 scoped 全局样式上色 -->
<style>
.at-cursor-bar {
  background: rgba(55, 153, 135, 0.18) !important;
  border-left: 2px solid rgba(39, 125, 111, 0.9) !important;
  z-index: 5;
  pointer-events: none !important;
}
.at-cursor-beat {
  background: rgba(55, 153, 135, 0.22) !important;
  z-index: 4;
  pointer-events: none !important;
}
</style>
