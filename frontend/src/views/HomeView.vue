<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useWorkbenchStore } from '../stores/workbench'
import {
  NAlert,
  NButton,
  NDropdown,
  NInput,
  NInputNumber,
  NProgress,
  NSelect,
  NModal,
  useDialog,
  useMessage,
} from 'naive-ui'
import { sampleMidiUrl } from '../samples/sampleSheet.js'
import ScoreViewer from '../components/ScoreViewer.vue'
import PlayerBar from '../components/PlayerBar.vue'
import MechanicalMetronome from '../components/MechanicalMetronome.vue'
import NoteEditor from '../components/NoteEditor.vue'
import type { NoteSelection } from '../services/noteEditing'
import { BeatClock } from '../services/beatClock'
import { readPreferences, savePreferences } from '../services/readerPreferences'
import {
  artifactUrl,
  deleteScore,
  getHealth,
  getScore,
  getScores,
  getTask,
  renameScore,
  transcribe,
  importScore,
  regenerateScore,
  ApiError,
} from '../services/transcribe'
import type { ArtifactType, ScoreSummary, ScoreOptions } from '../services/transcribe'
import { createPlaybackRange } from '../services/playbackRange'

const message = useMessage(),
  dialog = useDialog()
const store = useWorkbenchStore()
const {
  score,
  scores,
  health,
  task,
  taskId,
  bpm,
  timeSignature,
  quantization,
  error,
  viewMode,
  libraryCollapsed,
} = storeToRefs(store)
const viewer = ref<InstanceType<typeof ScoreViewer> | null>(null),
  fileInput = ref<HTMLInputElement | null>(null)
const viewerApiReady = ref(false)
const pendingScoreLoad = ref<{
  url: string
  title: string
  preferences: { bar: number; scale: number }
} | null>(null)
const search = ref(''),
  mobileLibraryOpen = ref(false),
  page = ref(0),
  totalPages = ref(0),
  busy = ref(false),
  current = ref(0),
  playing = ref(false),
  ready = ref(false)
const sourceAudio = ref<HTMLAudioElement | null>(null)
const originalAudioReady = ref(false)
const originalDuration = ref(0)
const audioSource = ref<'score' | 'original'>('score')
const originalAudioActive = ref(false)
const speed = ref(1),
  looping = ref(false)
const pointA = ref<{ tick: number; seconds: number } | null>(null),
  pointB = ref<{ tick: number; seconds: number } | null>(null),
  rangeError = ref('')
const metro = ref({ enabled: false, bpm: 120, subdivisions: 1, meter: '4/4' })
const metroCollapsed = ref(false)
const metroAngle = ref(18),
  metroBeat = ref(0)
const beatClock = new BeatClock((angle, beat) => {
  metroAngle.value = angle
  metroBeat.value = beat
})
const countClock = new BeatClock((_angle, beat) => {
  countBeat.value = beat
})
const countBeat = ref(0),
  countingIn = ref(false),
  countInEnabled = ref(false)
const loadingScore = ref(false),
  completedScoreId = ref(''),
  pollError = ref('')
const focusMode = ref(false),
  optionsOpen = ref(false),
  practiceOpen = ref(false),
  rescoring = ref(false)
const healthChecked = ref(false)
const rightVolume = ref(100),
  leftVolume = ref(100)
const rescoreOptions = ref<ScoreOptions>({
  bpm: 120,
  time_signature: '4/4',
  quantization: 16,
  hand_split: 64,
  key_fifths: null,
})
const readingState = ref({ bar: 0, scale: 0.9 })
const separateHands = ref(false)
const editorOpen = ref(false),
  editorSelection = ref<NoteSelection | null>(null)
const editor = ref<InstanceType<typeof NoteEditor> | null>(null)
const auditionRange = ref<{ start: number; end: number } | null>(null)
const compactScreen = window.matchMedia('(max-width:1100px)')
function useCompactLayout() {
  if (compactScreen.matches) {
    libraryCollapsed.value = true
    metroCollapsed.value = true
  }
}
let selectionGeneration = 0,
  selectionAbort: AbortController | null = null
const titleEdit = ref(false),
  titleDraft = ref('')
let pollTimer = 0,
  healthTimer = 0,
  handledCompletionId = ''
const displayTitle = computed(() => (score.value?.title || '').replaceAll('_', ' '))
const playerReady = computed(() =>
  audioSource.value === 'original' ? originalAudioReady.value : ready.value,
)
const playerDuration = computed(() =>
  Math.max(
    1,
    audioSource.value === 'original'
      ? originalDuration.value || score.value?.duration || 0
      : score.value?.duration || 0,
  ),
)
const visibleScores = computed(() =>
  scores.value.filter((s) =>
    (s.title || '').replaceAll('_', ' ').toLowerCase().includes(search.value.toLowerCase()),
  ),
)
function formatBpm(value?: number): string {
  if (value == null) return '—'
  return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(2)))
}
const stageLabels: Record<string, string> = {
  queued: '排队',
  running: '处理中',
  decoding: '解码',
  transcribing: '转录',
  scoring: '生成乐谱',
  completed: '完成',
  failed: '失败',
}
const taskStageText = computed(
  () => stageLabels[task.value?.stage || task.value?.status || ''] || task.value?.stage || '处理中',
)
const taskStatusText = computed(
  () => stageLabels[task.value?.status || ''] || task.value?.status || '就绪',
)

async function refreshScores(): Promise<void> {
  try {
    scores.value = await getScores()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}
async function refreshHealth(): Promise<void> {
  try {
    health.value = await getHealth()
  } catch {
    health.value = null
  } finally {
    healthChecked.value = true
  }
}
async function pollTask(): Promise<void> {
  if (!taskId.value) return
  const polledId = taskId.value
  try {
    const t = await getTask(polledId)
    if (polledId !== taskId.value) return
    pollError.value = ''
    store.updateTask(t)
    if (t.status === 'completed') {
      if (handledCompletionId === t.id) return
      handledCompletionId = t.id
      clearInterval(pollTimer)
      busy.value = false
      store.clearTask()
      await Promise.all([refreshScores(), refreshHealth()])
      if (t.score_id) {
        if (viewMode.value === 'import') await openScore(t.score_id)
        else {
          completedScoreId.value = t.score_id
          message.success('转录完成，可打开新乐谱')
        }
      }
    } else if (t.status === 'failed') {
      clearInterval(pollTimer)
      busy.value = false
      error.value = t.error || '转录失败'
    }
  } catch (e) {
    if (polledId !== taskId.value) return
    if (e instanceof ApiError && e.status === 404) {
      store.clearTask()
      busy.value = false
      error.value = '此任务已不存在，请重新提交音频'
    } else {
      pollError.value = '暂时无法查询任务，将自动重试。你可以继续阅读已有乐谱。'
    }
  }
}
function beginPolling(): void {
  clearTimeout(pollTimer)
  const next = async () => {
    await pollTask()
    if (taskId.value && busy.value) pollTimer = window.setTimeout(next, 1800)
  }
  void next()
}
async function upload(file?: File): Promise<void> {
  if (!file || busy.value) return
  if (file.size === 0 || file.size > 100 * 1024 * 1024) {
    error.value = '请选择非空且不超过 100 MB 的音频'
    return
  }
  if (!/^audio\//.test(file.type) && !/\.(wav|mp3|m4a|flac|ogg|aac|webm)$/i.test(file.name)) {
    error.value = '请选择音频文件'
    return
  }
  error.value = ''
  store.setViewMode('import')
  busy.value = true
  handledCompletionId = ''
  store.retryFile = file
  store.startTask({ id: 'pending', status: 'queued', stage: '正在提交' })
  try {
    const r = await transcribe(file, {
      bpm: bpm.value,
      time_signature: timeSignature.value,
      quantization: quantization.value,
    })
    store.rememberTask(r.task_id, file)
    beginPolling()
  } catch (e) {
    busy.value = false
    store.clearTask()
    error.value = e instanceof Error ? e.message : String(e)
  }
}
async function importFile(file?: File): Promise<void> {
  if (!file) return
  if (/\.(xml|musicxml|mxl)$/i.test(file.name)) {
    if (busy.value) return
    if (file.size > 10 * 1024 * 1024) {
      error.value = '乐谱不能超过 10 MB'
      return
    }
    busy.value = true
    error.value = ''
    try {
      const saved = await importScore(file)
      await refreshScores()
      await openScore(saved.id)
      message.success('乐谱已保存到曲库')
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      busy.value = false
    }
    return
  }
  upload(file)
}
function chooseFile(): void {
  fileInput.value?.click()
}
async function openScore(id: string): Promise<void> {
  if (score.value?.id !== id) {
    if (!(await confirmDiscardEdits())) return
    editorOpen.value = false
    editorSelection.value = null
  }
  const generation = ++selectionGeneration
  selectionAbort?.abort()
  selectionAbort = new AbortController()
  cancelCountIn()
  sourceAudio.value?.pause()
  viewer.value?.pause()
  loadingScore.value = true
  error.value = ''
  try {
    const detail = await getScore(id, selectionAbort.signal)
    if (generation !== selectionGeneration) return
    score.value = detail
    titleEdit.value = false
    optionsOpen.value = false
    const preferences = readPreferences(id)
    readingState.value = { bar: preferences.bar, scale: preferences.scale }
    metroCollapsed.value = preferences.metroCollapsed
    rescoreOptions.value = {
      bpm: detail.bpm || 120,
      time_signature: detail.time_signature || '4/4',
      quantization: detail.settings?.quantization || 16,
      hand_split: detail.settings?.hand_split || 64,
      key_fifths: detail.settings?.key_fifths ?? null,
    }
    rightVolume.value = 100
    leftVolume.value = 100
    titleDraft.value = (detail.title || '').replaceAll('_', ' ')
    localStorage.setItem('lingpu.scoreId', id)
    store.setViewMode('reader')
    await loadIntoViewer(artifactUrl(id, 'musicxml') + `?v=${Date.now()}`, displayTitle.value)
  } catch (e) {
    if (generation !== selectionGeneration || (e instanceof Error && e.name === 'AbortError'))
      return
    loadingScore.value = false
    error.value = e instanceof Error ? e.message : String(e)
  }
}
function openCompletedScore() {
  const id = completedScoreId.value
  completedScoreId.value = ''
  void openScore(id)
}
function loadSample(): void {
  selectionGeneration++
  selectionAbort?.abort()
  cancelCountIn()
  readingState.value = { bar: 0, scale: 0.9 }
  localStorage.removeItem('lingpu.scoreId')
  score.value = { title: '示例乐谱' }
  store.setViewMode('reader')
  void loadIntoViewer(sampleMidiUrl, '示例乐谱')
}
async function loadIntoViewer(url: string, title: string): Promise<void> {
  await nextTick()
  if (!viewerApiReady.value || !viewer.value) {
    pendingScoreLoad.value = { url, title, preferences: readingState.value }
    return
  }
  pendingScoreLoad.value = null
  await viewer.value.loadScore(url, title, readingState.value)
}
function onViewerApiReady(isReady: boolean): void {
  viewerApiReady.value = isReady
  if (!isReady || !pendingScoreLoad.value || !viewer.value) return
  const pending = pendingScoreLoad.value
  pendingScoreLoad.value = null
  void viewer.value.loadScore(pending.url, pending.title, pending.preferences)
}
function retry(): void {
  if (store.retryFile) upload(store.retryFile)
  else chooseFile()
}
async function saveTitle(): Promise<void> {
  if (!score.value?.id) return
  try {
    await renameScore(score.value.id, titleDraft.value.trim())
    titleEdit.value = false
    await refreshScores()
    await openScore(score.value.id)
  } catch (e) {
    message.error(e instanceof Error ? e.message : String(e))
  }
}
function removeScore(item: ScoreSummary): void {
  dialog.warning({
    title: '删除乐谱',
    content: `确定删除「${item.title}」？`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await deleteScore(item.id)
        if (score.value?.id === item.id) {
          editorOpen.value = false
          viewer.value?.clearScore()
          store.clearScore()
          localStorage.removeItem('lingpu.scoreId')
          leaveReader()
        }
        await refreshScores()
        message.success('已删除')
      } catch (e) {
        message.error(e instanceof Error ? e.message : String(e))
      }
    },
  })
}
function onStats(s: { title: string; durationMs: number; tracks?: number }): void {
  if (!s) return
  separateHands.value = (s.tracks ?? 0) >= 2
  if (!score.value) score.value = { title: s.title, duration: s.durationMs / 1000 }
  else score.value = { ...score.value, duration: s.durationMs / 1000 }
}
function clearStats(): void {
  store.clearScore()
  resetPlaybackUI()
}
function resetPlaybackUI(): void {
  auditionRange.value = null
  cancelCountIn()
  originalAudioActive.value = false
  sourceAudio.value?.pause()
  audioSource.value = 'score'
  originalAudioReady.value = false
  originalDuration.value = 0
  ready.value = false
  playing.value = false
  current.value = 0
  speed.value = 1
  looping.value = false
  pointA.value = null
  pointB.value = null
  rangeError.value = ''
  void nextTick().then(onOriginalAudioMetadata)
}
function setPointA(): void {
  if (!ready.value) return
  const tick = viewer.value?.currentTick() ?? 0
  pointA.value = { tick, seconds: current.value }
  pointB.value = null
  rangeError.value = ''
  viewer.value?.clearPlaybackRange()
  looping.value = false
}
function setPointB(): void {
  if (!ready.value || !pointA.value) return
  const tick = viewer.value?.currentTick() ?? 0
  const range = createPlaybackRange(pointA.value.tick, tick)
  if (!range) {
    pointB.value = null
    rangeError.value = 'B 点须晚于 A 点'
    return
  }
  if (!viewer.value?.setPlaybackRange(range.startTick, range.endTick)) {
    pointB.value = null
    rangeError.value = '无法设置此选段'
    return
  }
  pointB.value = { tick, seconds: current.value }
  rangeError.value = ''
  looping.value = true
}
function clearRange(): void {
  viewer.value?.clearPlaybackRange()
  pointA.value = null
  pointB.value = null
  rangeError.value = ''
  looping.value = false
}
function setLoop(enabled: boolean): void {
  viewer.value?.setLoop(enabled)
  looping.value = enabled
}
function setSpeed(rate: number): void {
  if (sourceAudio.value) sourceAudio.value.playbackRate = rate
  viewer.value?.setSpeed(rate)
  speed.value = rate
}
function syncOriginalAudio(forceFollow = false): void {
  const audio = sourceAudio.value
  if (!audio || !originalAudioActive.value) return
  if (auditionRange.value && audio.currentTime >= auditionRange.value.end) {
    audio.pause()
    auditionRange.value = null
  }
  if (looping.value && pointA.value && pointB.value && audio.currentTime >= pointB.value.seconds) {
    audio.currentTime = pointA.value.seconds
    return
  }
  current.value = audio.currentTime
  viewer.value?.followOriginalAudio(audio.currentTime, forceFollow)
}
function onOriginalAudioTimeUpdate(): void {
  syncOriginalAudio()
}
function onOriginalAudioPlay(): void {
  if (audioSource.value !== 'original') {
    sourceAudio.value?.pause()
    return
  }
  originalAudioActive.value = true
  viewer.value?.pause()
  if (sourceAudio.value) sourceAudio.value.playbackRate = speed.value
  playing.value = true
  syncOriginalAudio()
}
function onOriginalAudioSeek(): void {
  if (audioSource.value !== 'original') return
  originalAudioActive.value = true
  viewer.value?.pause()
  playing.value = sourceAudio.value ? !sourceAudio.value.paused : false
  syncOriginalAudio(true)
}
function onOriginalAudioPause(): void {
  if (audioSource.value !== 'original') return
  if (!originalAudioActive.value) return
  if (sourceAudio.value && !sourceAudio.value.paused) {
    playing.value = true
    return
  }
  playing.value = false
  syncOriginalAudio()
}
function onOriginalAudioEnded(): void {
  const audio = sourceAudio.value
  if (looping.value && audio) {
    audio.currentTime = pointA.value?.seconds ?? 0
    void audio.play().catch((e: unknown) => {
      error.value = e instanceof Error ? e.message : '原音循环播放失败'
    })
    return
  }
  onOriginalAudioPause()
}
function onScorePlayState(state: number): void {
  if (!originalAudioActive.value) playing.value = state === 1
}
function onScoreTime(seconds: number): void {
  if (!originalAudioActive.value) current.value = seconds
}
async function togglePlayback(): Promise<void> {
  if (countingIn.value) {
    cancelCountIn()
    return
  }
  if (!playing.value && countInEnabled.value) {
    countingIn.value = true
    if (metro.value.enabled) {
      metro.value.enabled = false
      stopMetro()
    }
    try {
      const complete = await countClock.start(
        {
          bpm: (score.value?.bpm || 120) * speed.value,
          meter: score.value?.time_signature || '4/4',
          subdivisions: 1,
        },
        1,
      )
      countingIn.value = false
      if (!complete) return
    } catch {
      countingIn.value = false
      error.value = '无法启动预备拍，请允许浏览器播放声音'
      return
    }
  }
  if (audioSource.value === 'original') {
    const audio = sourceAudio.value
    if (!audio || !originalAudioReady.value) return
    if (!audio.paused) {
      audio.pause()
    } else {
      viewer.value?.pause()
      void audio.play().catch((e: unknown) => {
        error.value = e instanceof Error ? e.message : '原音播放失败'
      })
    }
    return
  }
  originalAudioActive.value = false
  sourceAudio.value?.pause()
  viewer.value?.togglePlay()
}
function seekPlayback(seconds: number): void {
  if (audioSource.value === 'original' && sourceAudio.value) {
    sourceAudio.value.currentTime = Math.min(seconds, sourceAudio.value.duration || seconds)
    syncOriginalAudio()
  } else viewer.value?.seek(seconds)
}
function selectAudioSource(source: 'score' | 'original'): void {
  if (source === audioSource.value) return
  if (source === 'original' && !originalAudioReady.value) return
  sourceAudio.value?.pause()
  originalAudioActive.value = false
  viewer.value?.pause()
  cancelCountIn()
  const position = Math.min(
    current.value,
    source === 'original' ? originalDuration.value : score.value?.duration || current.value,
  )
  if (sourceAudio.value && originalAudioReady.value) sourceAudio.value.currentTime = position
  viewer.value?.seek(position)
  current.value = position
  playing.value = false
  audioSource.value = source
}
function onOriginalAudioMetadata(): void {
  if (score.value?.has_audio === false) {
    originalAudioReady.value = false
    originalDuration.value = 0
    return
  }
  const duration = sourceAudio.value?.duration ?? 0
  originalDuration.value = Number.isFinite(duration) ? duration : 0
  originalAudioReady.value = originalDuration.value > 0 && (sourceAudio.value?.readyState ?? 0) >= 1
}
async function leaveReader(): Promise<void> {
  if (!(await confirmDiscardEdits())) return
  editorOpen.value = false
  editorSelection.value = null
  auditionRange.value = null
  selectionGeneration++
  selectionAbort?.abort()
  pendingScoreLoad.value = null
  loadingScore.value = false
  cancelCountIn()
  originalAudioActive.value = false
  sourceAudio.value?.pause()
  viewer.value?.pause()
  viewer.value?.stop()
  viewer.value?.clearPlaybackRange()
  viewer.value?.setLoop(false)
  viewer.value?.setSpeed(1)
  playing.value = false
  current.value = 0
  audioSource.value = 'score'
  originalAudioReady.value = false
  originalDuration.value = 0
  speed.value = 1
  looping.value = false
  pointA.value = null
  pointB.value = null
  rangeError.value = ''
  metro.value.enabled = false
  stopMetro()
  store.setViewMode('import')
}
function onPageChange(payload: { page: number; total: number }): void {
  page.value = payload.page
  totalPages.value = payload.total
}
function handlePageKeys(event: KeyboardEvent): void {
  if (event.key === 'Escape') focusMode.value = false
  if (
    viewMode.value !== 'reader' ||
    !totalPages.value ||
    event.altKey ||
    event.ctrlKey ||
    event.metaKey
  )
    return
  const target = event.target
  if (
    target instanceof HTMLElement &&
    (target.isContentEditable ||
      target.closest(
        'input,textarea,select,[contenteditable=true],[role=combobox],[role=listbox],.n-modal,.n-dialog',
      ))
  )
    return
  if (event.key === 'ArrowLeft') {
    event.preventDefault()
    viewer.value?.previousPage()
  } else if (event.key === 'ArrowRight') {
    event.preventDefault()
    viewer.value?.nextPage()
  } else if (
    event.code === 'Space' &&
    !(target instanceof HTMLElement && target.closest('button, a, [role="button"]'))
  ) {
    event.preventDefault()
    void togglePlayback()
  }
}
function loadFail(message: string): void {
  loadingScore.value = false
  error.value = message
}
function download(type: ArtifactType | 'pdf'): void {
  if (type === 'pdf') {
    viewer.value?.printScore()
    return
  }
  if (score.value?.id) window.open(artifactUrl(score.value.id, type), '_blank', 'noopener')
}
function stopMetro(): void {
  beatClock.stop()
}
async function startMetro(): Promise<void> {
  stopMetro()
  if (!metro.value.enabled) return
  try {
    await beatClock.start(metro.value)
  } catch {
    metro.value.enabled = false
    message.error('节拍器无法发声，请允许浏览器播放声音')
  }
}
function changeMetro(): void {
  if (metro.value.enabled) startMetro()
  else stopMetro()
}
function cancelCountIn() {
  countClock.stop()
  countingIn.value = false
}
function onReadingChange(value: { bar: number; scale: number }) {
  if (loadingScore.value) return
  readingState.value = value
  rememberReading()
}
function rememberReading() {
  if (score.value?.id && !loadingScore.value)
    savePreferences(score.value.id, { ...readingState.value, metroCollapsed: metroCollapsed.value })
}
function onViewerRendered() {
  loadingScore.value = false
  onOriginalAudioMetadata()
  viewer.value?.setHandVolumes(rightVolume.value, leftVolume.value)
}
function confirmDiscardEdits(): Promise<boolean> {
  if (editor.value?.isWorking()) {
    message.info('正在保存，请稍候再切换曲目')
    return Promise.resolve(false)
  }
  if (!editor.value?.hasChanges()) return Promise.resolve(true)
  return new Promise((resolve) =>
    dialog.warning({
      title: '保留音符修改？',
      content: '当前音符修改尚未保存。离开会放弃这些修改。',
      positiveText: '放弃并离开',
      negativeText: '继续编辑',
      onPositiveClick: () => resolve(true),
      onNegativeClick: () => resolve(false),
      onClose: () => resolve(false),
      onMaskClick: () => resolve(false),
    }),
  )
}
const editorTopSize = ref(0.8)
let stopEditorResize = () => {}
function resizeEditor(event: PointerEvent) {
  event.preventDefault()
  const bounds = (event.currentTarget as HTMLElement).closest('.reader-body')!.getBoundingClientRect()
  const move = (e: PointerEvent) => { editorTopSize.value = Math.max(0.4, Math.min(1.5, (e.clientY - bounds.top - 70) / Math.max(1, bounds.height - 100) * 1.8)) }
  const stop = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', stop); window.removeEventListener('pointercancel', stop) }
  stopEditorResize()
  stopEditorResize = stop
  window.addEventListener('pointermove', move)
  window.addEventListener('pointerup', stop)
  window.addEventListener('pointercancel', stop)
}
async function toggleEditor() {
  if (editorOpen.value) {
    if (!(await confirmDiscardEdits())) return
    editorOpen.value = false
    editorSelection.value = null
    sourceAudio.value?.pause()
    auditionRange.value = null
  } else {
    cancelCountIn()
    viewer.value?.pause()
    sourceAudio.value?.pause()
    editorOpen.value = true
    practiceOpen.value = false
  }
}
function selectEditorNote(selection: NoteSelection) {
  cancelCountIn()
  viewer.value?.pause()
  sourceAudio.value?.pause()
  editorSelection.value = selection
}
async function editorSaved() {
  const id = score.value?.id,
    version = selectionGeneration
  if (!id) return
  editorSelection.value = null
  await refreshScores()
  if (version !== selectionGeneration || score.value?.id !== id) return
  await openScore(id)
  message.success('已更新乐谱与导出文件')
}
async function listenEditorRange(range: { start: number; end: number }) {
  if (!sourceAudio.value || !originalAudioReady.value) {
    message.info('原音尚未加载完成')
    return
  }
  cancelCountIn()
  clearRange()
  viewer.value?.pause()
  selectAudioSource('original')
  auditionRange.value = range
  sourceAudio.value.currentTime = range.start
  try {
    await sourceAudio.value.play()
  } catch {
    message.error('原音播放失败，请重试')
  }
}
function protectUnsaved(event: BeforeUnloadEvent) {
  if (editor.value?.hasChanges() || editor.value?.isWorking()) {
    event.preventDefault()
    event.returnValue = ''
  }
}
function onViewerReady(value: boolean) {
  ready.value = value
  if (value) viewer.value?.setHandVolumes(rightVolume.value, leftVolume.value)
}
function updateHands() {
  viewer.value?.setHandVolumes(rightVolume.value, leftVolume.value)
}
async function rebuildScore() {
  if (!score.value?.id || rescoring.value) return
  const id = score.value.id
  rescoring.value = true
  error.value = ''
  cancelCountIn()
  viewer.value?.pause()
  sourceAudio.value?.pause()
  try {
    await regenerateScore(id, rescoreOptions.value)
    await refreshScores()
    await openScore(id)
    message.success('已重新生成乐谱，原录音和原始转录事件已保留')
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    rescoring.value = false
  }
}
async function toggleFullscreen() {
  try {
    if (document.fullscreenElement) await document.exitFullscreen()
    else await document.querySelector('.app-shell')?.requestFullscreen()
  } catch {
    message.info('当前浏览器未提供全屏支持，可使用专注模式')
  }
}
watch(metroCollapsed, rememberReading)
watch(libraryCollapsed, (value) => localStorage.setItem('lingpu.libraryCollapsed', String(value)))
function onAudioInput(event: Event): void {
  const input = event.target
  if (!(input instanceof HTMLInputElement)) return
  importFile(input.files?.[0])
  input.value = ''
}
function onFileDrop(event: DragEvent): void {
  importFile(event.dataTransfer?.files[0])
}
onMounted(() => {
  window.addEventListener('beforeunload', protectUnsaved)
  useCompactLayout()
  compactScreen.addEventListener('change', useCompactLayout)
  refreshHealth()
  refreshScores()
  window.addEventListener('keydown', handlePageKeys)
  const savedScoreId = localStorage.getItem('lingpu.scoreId')
  if (savedScoreId && viewMode.value === 'reader') void openScore(savedScoreId)
  else if (taskId.value) store.setViewMode('import')
  else if (viewMode.value === 'reader' && !savedScoreId) store.setViewMode('import')
  healthTimer = window.setInterval(refreshHealth, 15000)
  if (taskId.value) {
    busy.value = true
    beginPolling()
  }
})
onBeforeUnmount(() => {
  stopEditorResize()
  window.removeEventListener('beforeunload', protectUnsaved)
  compactScreen.removeEventListener('change', useCompactLayout)
  clearInterval(pollTimer)
  clearInterval(healthTimer)
  window.removeEventListener('keydown', handlePageKeys)
  stopMetro()
  selectionAbort?.abort()
  beatClock.dispose()
  countClock.dispose()
  originalAudioActive.value = false
  sourceAudio.value?.pause()
  viewer.value?.pause()
})
</script>

<template>
  <div
    class="app-shell"
    :class="[
      `mode-${viewMode}`,
      {
        'library-collapsed': libraryCollapsed,
        'mobile-library-open': mobileLibraryOpen,
        'focus-mode': focusMode && !editorOpen,
        'correction-mode': editorOpen,
      },
    ]"
  >
    <aside class="sidebar">
      <a class="brand" href="/" @click.prevent="leaveReader">灵谱</a>
      <button
        class="library-collapse"
        :aria-label="libraryCollapsed ? '展开曲库' : '收起曲库'"
        :title="libraryCollapsed ? '展开曲库' : '收起曲库'"
        @click="libraryCollapsed = !libraryCollapsed"
      >
        {{ libraryCollapsed ? '›' : '‹' }}
      </button>
      <n-button
        class="mobile-library-toggle"
        size="small"
        secondary
        @click="mobileLibraryOpen = !mobileLibraryOpen"
        >{{ mobileLibraryOpen ? '收起曲库' : '曲库' }}</n-button
      >
      <div class="library-head">
        <span>我的曲库</span><n-button text size="tiny" @click="refreshScores">↻</n-button>
      </div>
      <button
        class="nav import-nav"
        :class="{ active: viewMode === 'import' }"
        title="导入"
        aria-label="导入"
        @click="leaveReader"
      >
        ＋ <span>导入</span>
      </button>
      <n-input v-model:value="search" size="small" placeholder="搜索乐谱" clearable />
      <div class="score-list">
        <div
          v-for="item in visibleScores"
          :key="item.id"
          class="score-entry"
          :class="{ selected: score?.id === item.id }"
          @click="openScore(item.id)"
        >
          <span class="score-icon">♫</span
          ><span class="entry-copy"
            ><b>{{ item.title.replaceAll('_', ' ') }}</b
            ><small>{{ formatBpm(item.bpm) }} BPM · {{ item.note_count || 0 }} 音符</small></span
          >
          <n-dropdown :options="[{ label: '删除', key: 'delete' }]" @select="removeScore(item)"
            ><button class="more" @click.stop>···</button></n-dropdown
          >
        </div>
        <div v-if="!visibleScores.length" class="empty-list">
          {{ search ? '没有找到匹配乐谱' : '曲库暂时为空' }}
        </div>
      </div>
    </aside>
    <main class="workspace">
      <header v-if="viewMode === 'import'" class="topbar">
        <div>
          <h1>导入与转录</h1>
        </div>
      </header>
      <section v-show="viewMode === 'import'" class="import-page">
        <input
          ref="fileInput"
          type="file"
          accept="audio/*,.musicxml,.xml,.mxl"
          hidden
          @change="onAudioInput"
        />
        <section class="import-card" @dragover.prevent @drop.prevent="onFileDrop">
          <div class="upload-mark">↑</div>
          <h2>把音频变成可练习的钢琴谱</h2>
          <p>支持音频转录，也可直接导入 MusicXML 文件。</p>
          <div class="import-actions">
            <n-button type="primary" :loading="busy" :disabled="busy" @click="chooseFile"
              >选择音频或 MusicXML</n-button
            ><n-button secondary @click="loadSample">打开示例乐谱</n-button>
          </div>
          <div class="drop-hint">也可以将文件拖放到此处</div>
        </section>
        <section class="setting-card import-settings">
          <div class="section-title">转录参数</div>
          <div class="setting-row">
            <span>目标 BPM</span
            ><n-input-number
              v-model:value="bpm"
              :min="30"
              :max="300"
              size="small"
              placeholder="自动"
            />
          </div>
          <div class="setting-row">
            <span>拍号</span
            ><n-select
              v-model:value="timeSignature"
              size="small"
              :options="[
                { label: '4/4', value: '4/4' },
                { label: '3/4', value: '3/4' },
                { label: '6/8', value: '6/8' },
              ]"
            />
          </div>
          <div class="setting-row">
            <span>量化</span
            ><n-select
              v-model:value="quantization"
              size="small"
              :options="[
                { label: '1/8', value: 8 },
                { label: '1/16', value: 16 },
                { label: '1/32', value: 32 },
              ]"
            />
          </div>
        </section>
        <section v-if="taskId || (busy && store.retryFile)" class="setting-card task-card">
          <div class="section-title">
            转录任务 <span>{{ taskStatusText }}</span>
          </div>
          <div>{{ task ? taskStageText : '正在提交任务' }}</div>
          <small v-if="pollError">{{ pollError }}</small>
          <n-progress
            v-if="task?.progress != null"
            type="line"
            :percentage="task.progress"
            :show-indicator="true"
          /><small v-if="task?.elapsed_seconds != null"
            >已用时 {{ Math.round(task.elapsed_seconds) }} 秒</small
          ><n-button v-if="task?.status === 'failed'" size="small" type="primary" @click="retry"
            >重试转录</n-button
          >
        </section>
        <section class="setting-card status-card">
          <div class="section-title">服务状态</div>
          <div class="status-line">
            <span class="health-dot" :class="{ good: health?.ready }" />{{
              health?.ready
                ? '服务正常'
                : health
                  ? '转录暂不可用'
                  : healthChecked
                    ? '无法连接服务'
                    : '连接中'
            }}
          </div>
          <small
            >{{ health?.model_loaded ? '模型已加载' : '等待模型状态' }} ·
            {{ health?.worker_alive ? '工作进程在线' : '工作进程离线' }}</small
          >
        </section>
        <n-alert v-if="error" type="error" closable class="error-alert" @close="error = ''"
          >{{ error }}
          <n-button v-if="store.retryFile" text type="error" @click="retry">重试</n-button></n-alert
        >
      </section>
      <section v-show="viewMode === 'reader'" class="reader-page">
        <n-alert v-if="completedScoreId" type="success" closable @close="completedScoreId = ''"
          >新乐谱已准备好 <n-button text @click="openCompletedScore">打开乐谱</n-button></n-alert
        >
        <n-alert v-if="error" type="error" closable class="error-alert" @close="error = ''">{{
          error
        }}</n-alert>
        <div
          class="reader-body"
          :class="{ 'tools-collapsed': metroCollapsed, editing: editorOpen }"
          :style="editorOpen ? { gridTemplateRows: `auto minmax(140px, ${editorTopSize}fr) minmax(220px, ${1.8 - editorTopSize}fr)` } : {}"
        >
          <section class="score-card">
            <button v-if="editorOpen" class="editor-splitter" aria-label="调整乐谱与时间图高度" @pointerdown="resizeEditor" @keydown.up.prevent="editorTopSize = Math.max(0.4, editorTopSize - 0.1)" @keydown.down.prevent="editorTopSize = Math.min(1.5, editorTopSize + 0.1)">↕</button>
            <div class="score-toolbar">
              <div class="toolbar-actions">
                <span class="page-controls">{{
                  totalPages ? `${page} / ${totalPages}` : '—'
                }}</span>
                <template v-if="score?.id">
                  <n-button text size="small" @click="titleEdit = !titleEdit">重命名</n-button>
                  <n-dropdown
                    :options="[
                      { label: '下载 MusicXML', key: 'musicxml' },
                      { label: '下载 MIDI', key: 'midi' },
                      ...(score.has_audio === false ? [] : [{ label: '下载音频', key: 'audio' }]),
                      { label: '打印 / 保存 PDF', key: 'pdf' },
                    ]"
                    @select="download"
                    ><n-button text size="small">导出</n-button></n-dropdown
                  >
                </template>
                <n-button text size="small" @click="practiceOpen = !practiceOpen">练习</n-button>
                <n-button
                  v-if="score?.can_regenerate"
                  text
                  size="small"
                  :type="editorOpen ? 'primary' : 'default'"
                  :disabled="loadingScore"
                  @click="toggleEditor"
                  >{{ editorOpen ? '结束纠错' : '纠错' }}</n-button
                >
                <n-dropdown
                  :options="[
                    { label: '适应宽度', key: 'width' },
                    { label: '适应整页', key: 'page' },
                    { label: '专注看谱', key: 'focus' },
                    { label: '切换全屏', key: 'fullscreen' },
                    ...(score?.can_regenerate && !editorOpen
                      ? [{ label: '重新生成乐谱', key: 'regenerate' }]
                      : []),
                  ]"
                  @select="
                    (key) =>
                      key === 'width'
                        ? viewer?.fitWidth()
                        : key === 'page'
                          ? viewer?.fitPage()
                          : key === 'focus'
                            ? (focusMode = true)
                            : key === 'fullscreen'
                              ? toggleFullscreen()
                              : (optionsOpen = true)
                  "
                  ><n-button text size="small">视图与设置</n-button></n-dropdown
                >
                <n-button
                  text
                  size="small"
                  title="缩小乐谱"
                  aria-label="缩小乐谱"
                  @click="viewer?.zoomOut()"
                  >−</n-button
                >
                <n-button
                  text
                  size="small"
                  title="放大乐谱"
                  aria-label="放大乐谱"
                  @click="viewer?.zoomIn()"
                  >＋</n-button
                >
              </div>
            </div>
            <div v-if="practiceOpen" class="practice-panel">
              <label
                >右手音量
                <n-input-number
                  v-model:value="rightVolume"
                  :min="0"
                  :max="100"
                  size="small"
                  :disabled="audioSource === 'original' || !separateHands"
                  @update:value="updateHands"
              /></label>
              <label
                >左手音量
                <n-input-number
                  v-model:value="leftVolume"
                  :min="0"
                  :max="100"
                  size="small"
                  :disabled="audioSource === 'original' || !separateHands"
                  @update:value="updateHands"
              /></label>
              <button
                class="practice-toggle"
                :aria-pressed="countInEnabled"
                @click="countInEnabled = !countInEnabled"
              >
                预备一小节：{{ countInEnabled ? '开' : '关' }}
              </button>
              <small v-if="audioSource === 'original'">左右手音量适用于合成乐谱播放</small>
              <small v-else-if="!separateHands">此谱未分成左右手音轨</small>
            </div>
            <div v-if="titleEdit" class="rename-row">
              <n-input v-model:value="titleDraft" size="small" @keyup.enter="saveTitle" /><n-button
                size="small"
                type="primary"
                @click="saveTitle"
                >保存</n-button
              >
            </div>
            <ScoreViewer
              ref="viewer"
              :display-title="displayTitle"
              :edit-mode="editorOpen"
              @on-stats="onStats"
              @on-load-fail="loadFail"
              @on-time="onScoreTime"
              @on-play-state="onScorePlayState"
              @on-ready="onViewerReady"
              @on-api-ready="onViewerApiReady"
              @on-cleared="clearStats"
              @on-score-loading="resetPlaybackUI"
              @on-page-change="onPageChange"
              @on-reading-change="onReadingChange"
              @on-rendered="onViewerRendered"
              @on-note-select="selectEditorNote"
            />
            <div v-if="loadingScore" class="score-loading" role="status">正在打开乐谱…</div>
            <div v-if="countingIn" class="count-in" role="status">{{ countBeat || '准备' }}</div>
            <div v-if="!score" class="score-placeholder">
              <span>♫</span><b>打开曲库中的乐谱</b><small>选择一首乐谱开始练习</small>
            </div>
          </section>
          <NoteEditor
            v-if="editorOpen && score?.id"
            ref="editor"
            :score-id="score.id"
            :title="displayTitle"
            :current="current"
            :selection="editorSelection"
            @saved="editorSaved"
            @select-time="(time) => viewer?.followOriginalAudio(time, true)"
            @close="toggleEditor"
            @listen-range="listenEditorRange"
          />
          <MechanicalMetronome
            v-else
            v-model="metro"
            v-model:collapsed="metroCollapsed"
            :angle="metroAngle"
            :beat="metroBeat"
            @change="changeMetro"
          />
        </div>
      </section>
      <footer v-if="viewMode === 'reader'" class="bottom-player">
        <audio
          ref="sourceAudio"
          hidden
          preload="metadata"
          :src="score?.id && score.has_audio !== false ? artifactUrl(score.id, 'audio') : undefined"
          @loadedmetadata="onOriginalAudioMetadata"
          @play="onOriginalAudioPlay"
          @pause="onOriginalAudioPause"
          @ended="onOriginalAudioEnded"
          @timeupdate="onOriginalAudioTimeUpdate"
          @seeked="onOriginalAudioSeek"
          aria-hidden="true"
        />
        <PlayerBar
          :duration="playerDuration"
          :current="current"
          :playing="playing"
          :ready="playerReady"
          :speed="speed"
          :source-mode="audioSource"
          :original-available="originalAudioReady"
          :loop="looping"
          :point-a="pointA?.seconds"
          :point-b="pointB?.seconds"
          :range-error="rangeError"
          @toggle="togglePlayback"
          @seek="seekPlayback"
          @speed="setSpeed"
          @loop="setLoop"
          @set-a="setPointA"
          @set-b="setPointB"
          @clear-range="clearRange"
          @source-change="selectAudioSource"
        />
      </footer>
    </main>
    <button v-if="focusMode" class="exit-focus" @click="focusMode = false">退出专注</button>
    <n-modal
      v-model:show="optionsOpen"
      preset="card"
      title="重新生成乐谱"
      style="width: min(440px, 92vw)"
    >
      <p>使用已有转录事件重新排谱。原录音与首次生成的文件会保留。</p>
      <div class="rescore-fields">
        <label>BPM<n-input-number v-model:value="rescoreOptions.bpm" :min="30" :max="300" /></label>
        <label
          >拍号<n-select
            v-model:value="rescoreOptions.time_signature"
            :options="[
              { label: '3/4', value: '3/4' },
              { label: '4/4', value: '4/4' },
              { label: '6/8', value: '6/8' },
            ]"
        /></label>
        <label
          >量化<n-select
            v-model:value="rescoreOptions.quantization"
            :options="[8, 16, 32].map((v) => ({ label: `1/${v}`, value: v }))"
        /></label>
        <label
          >双手分界 MIDI 音高<n-input-number
            v-model:value="rescoreOptions.hand_split"
            :min="36"
            :max="84"
        /></label>
        <label
          >调号<n-select
            v-model:value="rescoreOptions.key_fifths"
            clearable
            placeholder="自动估计"
            :options="
              Array.from({ length: 15 }, (_, i) => ({
                value: i - 7,
                label: i === 7 ? '无升降号' : i < 7 ? `${7 - i} 个降号` : `${i - 7} 个升号`,
              }))
            "
        /></label>
      </div>
      <n-button
        type="primary"
        :loading="rescoring"
        :disabled="!rescoreOptions.bpm || !rescoreOptions.hand_split"
        @click="rebuildScore"
        >生成并打开</n-button
      >
    </n-modal>
  </div>
</template>

<style scoped>
.app-shell {
  display: grid;
  grid-template-columns: 252px minmax(0, 1fr);
  height: 100vh;
  min-height: 100vh;
  overflow: hidden;
  background: #f1f5f4;
  color: #243747;
  font-family: Inter, 'PingFang SC', sans-serif;
}

.sidebar {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
  height: 100vh;
  padding: 20px 14px;
  background: #fff;
  border-right: 1px solid #e1e9ed;
  transition:
    width 0.2s,
    padding 0.2s;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 38px;
  padding: 0 9px;
  color: #223b49;
  font-size: 20px;
  font-weight: 750;
}

.brand-icon {
  display: grid;
  width: 32px;
  height: 32px;
  place-items: center;
  border-radius: 10px;
  background: #e2f2ee;
  color: #287866;
  font-size: 20px;
}

.library-collapse {
  position: absolute;
  top: 24px;
  right: 14px;
  display: grid;
  width: 28px;
  height: 28px;
  place-items: center;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: #617b79;
  font-size: 24px;
  line-height: 1;
  cursor: pointer;
}
.library-collapse:hover {
  background: #eaf4f1;
  color: #287866;
}

.nav {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 11px 13px;
  border: 0;
  border-radius: 9px;
  background: transparent;
  color: #58706f;
  cursor: pointer;
  font-weight: 600;
  text-align: left;
}

.nav.active,
.nav:hover {
  background: #eaf4f1;
  color: #287866;
}

.mobile-library-toggle {
  display: none;
}

.library-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 13px 5px 0;
  color: #687b87;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.4px;
}

.score-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  overflow: auto;
}

.score-entry {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  padding: 10px 7px;
  border-radius: 9px;
  cursor: pointer;
}

.score-entry:hover,
.score-entry.selected {
  background: #f0f6f5;
}

.score-icon {
  color: #519688;
  font-size: 18px;
}

.entry-copy {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
  gap: 4px;
}

.entry-copy b {
  overflow: hidden;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.entry-copy small,
.empty-list {
  color: #9aaab3;
  font-size: 11px;
}

.more {
  border: 0;
  background: transparent;
  color: #8496a0;
  cursor: pointer;
}

.empty-list {
  padding: 20px 0;
  text-align: center;
}

.sidebar-bottom {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-top: auto;
  padding: 14px 4px 0;
  border-top: 1px solid #edf1f3;
  color: #667984;
  font-size: 11px;
}

.sidebar-bottom small {
  margin-left: auto;
}

.health-dot,
.live-dot {
  display: inline-block;
  flex: none;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #d89b57;
}

.health-dot.good,
.live-dot {
  background: #47a887;
}

.workspace {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  padding: 0 28px;
}

.topbar {
  display: flex;
  flex: none;
  align-items: center;
  justify-content: space-between;
  height: 78px;
}

.eyebrow {
  margin-bottom: 5px;
  color: #8496a0;
  font-size: 11px;
  letter-spacing: 1px;
}

.topbar h1 {
  margin: 0;
  font-size: 21px;
  font-weight: 700;
}

.top-actions {
  display: flex;
  gap: 9px;
}

.import-page {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 260px;
  align-content: start;
  gap: 16px;
  width: min(760px, 100%);
  margin: 28px auto 30px;
}

.import-card,
.setting-card {
  padding: 20px;
  border: 1px solid #e2e9ed;
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 3px 14px #253b4708;
}

.import-card {
  display: flex;
  grid-column: 1 / -1;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 260px;
  border-style: dashed;
  border-color: #c9ddda;
  background: linear-gradient(145deg, #fff, #f7fbfa);
  text-align: center;
}

.upload-mark {
  display: grid;
  width: 42px;
  height: 42px;
  place-items: center;
  border-radius: 12px;
  background: #e6f4f0;
  color: #328675;
  font-size: 23px;
}

.import-card h2 {
  margin: 15px 0 5px;
  font-size: 19px;
}

.import-card p,
.drop-hint {
  margin: 4px 0;
  color: #8496a0;
  font-size: 12px;
}

.import-actions {
  display: flex;
  gap: 10px;
  margin: 13px 0 8px;
}

.import-settings {
  grid-row: 2;
}

.task-card,
.status-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.task-card {
  grid-column: 2;
}

.status-card {
  grid-column: 1 / -1;
}

.section-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 7px;
  font-size: 12px;
  font-weight: 700;
}

.setting-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 13px;
  color: #82929b;
  font-size: 11px;
}

.setting-row :deep(.n-select),
.setting-row :deep(.n-input-number) {
  width: 130px;
}

.status-line {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.status-card small,
.task-card small {
  color: #8b9ba3;
  font-size: 10px;
}

.error-alert {
  grid-column: 1 / -1;
}

.reader-page {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-height: 0;
  gap: 12px;
  padding-top: 18px;
  padding-bottom: 76px;
}
.practice-panel {
  display: flex;
  flex: none;
  gap: 14px;
  align-items: center;
  flex-wrap: wrap;
  padding: 12px 16px;
  background: #f7faf9;
  border-bottom: 1px solid #e3ece8;
  font-size: 12px;
}
.practice-panel label {
  display: flex;
  align-items: center;
  gap: 8px;
}
.practice-panel :deep(.n-input-number) {
  width: 90px;
}
.practice-toggle {
  padding: 7px 10px;
  border: 1px solid #dce8e4;
  border-radius: 8px;
  background: #fff;
  color: #42675f;
  cursor: pointer;
}
.practice-toggle[aria-pressed='true'] {
  background: #e3f2eb;
}
.score-loading {
  position: absolute;
  z-index: 3;
  inset: 44px 0 0;
  display: grid;
  place-items: center;
  background: #ffffffdc;
  color: #648279;
  font-size: 14px;
}
.count-in {
  position: absolute;
  z-index: 4;
  top: 40%;
  left: 50%;
  transform: translate(-50%, -50%);
  display: grid;
  place-items: center;
  width: 100px;
  height: 100px;
  border-radius: 50%;
  background: #287e6dea;
  color: #fff;
  font-size: 40px;
  box-shadow: 0 8px 32px #24374730;
}
.rescore-fields {
  display: grid;
  gap: 14px;
  margin: 20px 0;
}
.rescore-fields label {
  display: grid;
  grid-template-columns: 145px 1fr;
  align-items: center;
  gap: 10px;
}
.focus-mode {
  grid-template-columns: minmax(0, 1fr);
}
.focus-mode > .sidebar,
.focus-mode .practice-tools,
.focus-mode .bottom-player {
  display: none;
}
.focus-mode .reader-body {
  grid-template-columns: minmax(0, 1fr);
}
.focus-mode .reader-page {
  padding-bottom: 18px;
}
.exit-focus {
  position: fixed;
  z-index: 6;
  top: 27px;
  left: 50%;
  transform: translateX(-50%);
  padding: 5px 12px;
  border: 1px solid #dce8e4;
  border-radius: 8px;
  color: #42675f;
  background: #fff;
  cursor: pointer;
}

.reader-controls {
  display: flex;
  flex: none;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
}

.page-controls {
  display: flex;
  align-items: center;
  gap: 12px;
  color: #667984;
  font-size: 12px;
}

.reader-body {
  display: grid;
  flex: 1;
  grid-template-columns: minmax(0, 1fr) 250px;
  min-height: 0;
  gap: 14px;
}

.score-card {
  position: relative;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  border: 1px solid #e2e9ed;
  border-radius: 14px;
  background: #f1f4f5;
  box-shadow: 0 4px 20px #253b4709;
}

.score-card :deep(.at-scroll-viewport) {
  flex: 1;
  min-height: 0;
  height: 100%;
}

.score-toolbar {
  position: sticky;
  z-index: 2;
  top: 0;
  display: flex;
  flex: none;
  align-items: center;
  justify-content: flex-end;
  height: 44px;
  padding: 0 17px;
  border-bottom: 1px solid #edf1f3;
  background: #fff;
  color: #405662;
  font-size: 12px;
  font-weight: 650;
}

.score-toolbar > div:first-child {
  display: flex;
  align-items: center;
  gap: 8px;
}

.score-toolbar small {
  color: #97a6ae;
  font-weight: 400;
}

.toolbar-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.rename-row {
  display: flex;
  gap: 7px;
  padding: 10px 16px;
}

.score-placeholder {
  position: absolute;
  inset: 44px 0 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #a3b0b7;
  pointer-events: none;
}

.score-placeholder span {
  color: #d6e7e2;
  font-size: 40px;
}

.score-placeholder b {
  font-size: 13px;
  font-weight: 600;
}

.score-placeholder small {
  font-size: 11px;
}

.reader-body.tools-collapsed {
  grid-template-columns: minmax(0, 1fr) 48px;
}
.editor-splitter { position: absolute; bottom: 0; left: calc(50% - 20px); width: 40px; height: 18px; border: 1px solid #dce8e3; border-radius: 6px 6px 0 0; background: #f3f8f5; color: #398671; cursor: ns-resize; z-index: 4; touch-action: none; }
.app-shell.correction-mode { grid-template-columns: minmax(0, 1fr); }
.correction-mode > .sidebar { display: none; }
.correction-mode .bottom-player { left: 0; display: flex; }
.reader-body.editing { display: grid; grid-template-columns: minmax(0, 1fr) 320px; grid-template-rows: auto minmax(140px, 0.8fr) minmax(220px, 1fr); gap: 14px; }
.reader-body.editing .score-card { grid-column: 1; grid-row: 2; }
.reader-body.editing .score-toolbar { display: none; }
@media (max-width: 1100px) {
 .reader-body.editing { grid-template-columns: minmax(0, 1fr) 270px; gap: 10px; }
}

.bottom-player {
  position: fixed;
  z-index: 4;
  right: 0;
  bottom: 0;
  left: 252px;
  padding: 9px 26px;
  border-top: 1px solid #e2e9ed;
  background: #fff;
  box-shadow: 0 -5px 18px #2138440c;
}

.bottom-player :deep(.playerbar) {
  display: grid;
  grid-template-columns: auto auto minmax(100px, 1fr) auto;
  align-items: center;
  gap: 14px;
}

.bottom-player :deep(.tp-btn.main) {
  width: 38px;
  height: 38px;
}

.bottom-player :deep(.btn-row) {
  gap: 8px;
}

.bottom-player :deep(.time-row) {
  grid-column: 2;
}

.bottom-player :deep(.slider-wrap) {
  grid-column: 3;
}

.bottom-player :deep(.speed-wrap) {
  grid-column: 4;
}

.bottom-player :deep(.hint) {
  display: none;
}

.library-collapsed {
  grid-template-columns: 62px minmax(0, 1fr);
}

.library-collapsed .sidebar {
  align-items: center;
  padding-right: 8px;
  padding-left: 8px;
}

.library-collapsed .library-collapse {
  position: static;
  order: 0;
  flex: none;
}
.library-collapsed .brand {
  order: -1;
  padding: 0;
}

.library-collapsed .brand,
.library-collapsed .nav span,
.library-collapsed .library-head,
.library-collapsed .sidebar > :deep(.n-input),
.library-collapsed .score-list,
.library-collapsed .sidebar-bottom {
  display: none;
}

.library-collapsed .nav {
  width: 42px;
  justify-content: center;
  padding: 11px 0;
}

.library-collapsed .bottom-player {
  left: 62px;
}
@media (max-width: 1100px) {
  .bottom-player :deep(.playerbar) {
    grid-template-columns: auto auto minmax(55px, 1fr) auto;
    gap: 10px;
  }
  .bottom-player :deep(.extra-controls) {
    grid-column: 4;
  }
  .bottom-player :deep(.speed-wrap),
  .bottom-player :deep(.ab-row) {
    grid-column: auto;
  }
}

@media (max-width: 900px) {
  .app-shell {
    grid-template-columns: 210px minmax(0, 1fr);
  }

  .library-collapsed {
    grid-template-columns: 62px minmax(0, 1fr);
  }

  .import-page {
    grid-template-columns: 1fr 230px;
  }

  .bottom-player {
    left: 210px;
  }
}

@media (max-width: 680px) {
  .sidebar .library-collapse {
    display: none;
  }
  .app-shell,
  .library-collapsed {
    display: block;
    height: 100vh;
    overflow: auto;
  }

  .sidebar {
    position: sticky;
    z-index: 5;
    top: 0;
    display: flex;
    flex-direction: row;
    align-items: center;
    height: auto;
    min-height: 56px;
    padding: 8px 12px;
    gap: 8px;
  }

  .sidebar .brand {
    flex: 1;
  }

  .sidebar .nav {
    display: none;
  }

  .sidebar .nav.import-nav {
    display: flex;
    padding: 8px 10px;
  }

  .mobile-library-toggle {
    display: inline-flex;
  }

  .sidebar .library-head,
  .sidebar > :deep(.n-input),
  .sidebar .score-list,
  .sidebar .sidebar-bottom {
    display: none;
  }

  .mobile-library-open .sidebar {
    flex-wrap: wrap;
  }

  .mobile-library-open .sidebar .library-head,
  .mobile-library-open .sidebar > :deep(.n-input),
  .mobile-library-open .sidebar .score-list {
    display: flex;
    flex: 0 0 100%;
  }

  .mobile-library-open .sidebar > :deep(.n-input) {
    order: 3;
  }

  .mobile-library-open .sidebar .library-head {
    order: 2;
  }

  .mobile-library-open .sidebar .score-list {
    order: 4;
    max-height: 35vh;
  }

  .workspace {
    min-height: calc(100vh - 56px);
    padding: 0 12px;
  }

  .topbar {
    height: 65px;
  }

  .topbar h1 {
    font-size: 17px;
  }

  .import-page {
    grid-template-columns: 1fr;
    margin: 14px auto;
  }

  .import-card,
  .import-settings,
  .task-card,
  .status-card {
    grid-column: 1;
    grid-row: auto;
  }

  .import-card {
    min-height: 225px;
    padding: 16px;
  }

  .import-card h2 {
    font-size: 16px;
  }

  .reader-page {
    padding-bottom: 90px;
  }

  .reader-controls {
    flex-wrap: wrap;
  }

  .page-controls {
    order: 3;
    justify-content: center;
    width: 100%;
  }

  .reader-body {
    grid-template-columns: minmax(0, 1fr) 150px;
    gap: 8px;
  }
  .reader-body.tools-collapsed {
    grid-template-columns: minmax(0, 1fr) 48px;
  }
  .mechanical-metro {
    zoom: 0.6;
    margin: 12px auto;
  }

  .practice-tools .setting-card {
    padding: 10px;
  }

  .score-card {
    min-height: 360px;
  }

  .bottom-player {
    left: 0;
    padding: 7px 10px;
  }

  .bottom-player :deep(.playerbar) {
    grid-template-columns: auto auto minmax(40px, 1fr) auto;
  }

  .bottom-player :deep(.ab-row) {
    grid-column: 1 / -1;
    grid-row: 2;
  }
}
</style>
