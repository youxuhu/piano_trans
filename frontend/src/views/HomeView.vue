<script setup>
import { NButton, NSlider, NTag, NProgress } from 'naive-ui'
import { ref } from 'vue'
import ScoreViewer from '../components/ScoreViewer.vue'
import PlayerBar from '../components/PlayerBar.vue'
import { sampleMidiUrl } from '../samples/sampleSheet.js'
import { transcribe } from '../services/transcribe.js'

const viewer = ref(null)
const sheetStats = ref(null)
const loadError = ref('')
const playTime = ref(0)
const playing = ref(false)
const playerReady = ref(false)

// 上传转谱状态
const transcribing = ref(false)     // 是否正在“转谱”
const transcribePct = ref(0)        // 模拟进度
const transcribeMsg = ref('')       // 提示文案
const dragOver = ref(false)         // 是否拖拽悬停在 hero 上
const fileName = ref('')            // 最近一次上传的文件名

function zoom(delta) {
  viewer.value[delta > 0 ? 'zoomIn' : 'zoomOut']()
}

function onStats(stats) {
  sheetStats.value = stats
  playTime.value = 0
  // 乐谱载入完成后即可播放（音源就绪由 alphaTab 内部缓冲处理）
  playerReady.value = true
}
function onPlayState(state) {
  // PlayerState: Paused=0, Playing=1（乐曲播完回到 Paused/stopped）
  playing.value = state === 1
}
function onTime(t) {
  playTime.value = t
}
function togglePlay() {
  viewer.value?.togglePlay()
}
function seek(seconds) {
  viewer.value?.seek(seconds)
}
function onSpeed(speed) {
  viewer.value?.setSpeed(speed)
}
function onLoop(loop) {
  viewer.value?.setLoop(loop)
}

/* —— 上传 & 转谱 —— */
function handleFile(file) {
  if (transcribing.value) return
  loadError.value = ''
  transcribing.value = true
  transcribePct.value = 0
  transcribeMsg.value = '读取文件…'
  fileName.value = file ? file.name : ''

  // 模拟转谱进度（60 步内走完），让“分析音频→生成乐谱”的过程有反馈
  let step = 0
  const timer = setInterval(() => {
    step += 1
    transcribePct.value = Math.min(step * 6, 92)
    transcribeMsg.value =
      step < 5 ? '解析音频特征…'
      : step < 8 ? '识别音符与节拍…'
      : step < 11 ? '生成五线谱…' : '整理谱面…'
  }, 90)

  transcribe(file)
    .then(result => {
      clearInterval(timer)
      transcribePct.value = 100
      transcribeMsg.value = '转录完成 ✓'
      if (result.kind === 'score') {
        viewer.value?.loadScore(result.url)
      } else {
        viewer.value?.loadAlphaTex(result.text)
      }
      setTimeout(() => {
        transcribing.value = false
      }, 500)
    })
    .catch(err => {
      clearInterval(timer)
      transcribing.value = false
      loadError.value = err?.message || '转谱失败'
    })
}

const fileInput = ref(null)
function pickFile() {
  fileInput.value?.click()
}
function onInputChange(e) {
  const f = e?.target?.files?.[0]
  if (f) handleFile(f)
  if (e?.target) e.target.value = '' // 允许连续选同一文件
}
function onDrop(e) {
  dragOver.value = false
  const f = e?.dataTransfer?.files?.[0]
  if (f) handleFile(f)
}
function onDragEnter(e) {
  if (e?.dataTransfer?.types?.includes('Files')) dragOver.value = true
}
function onDragOver(e) {
  e?.preventDefault()
  if (e?.dataTransfer?.types?.includes('Files')) dragOver.value = true
}
function onDragLeave(e) {
  if (!e?.currentTarget?.contains(e?.relatedTarget)) dragOver.value = false
}
function loadSample() {
  loadError.value = ''
  viewer.value?.loadScore(sampleMidiUrl)
}

const steps = [
  { no: '01', name: '声音成谱', desc: '上传钢琴音频，AI 转录为五线谱' },
  { no: '02', name: '音画跟播', desc: '光标随音符同步滚动' },
  { no: '03', name: '节拍器', desc: 'BPM · 细分 · 强拍提示' },
]
</script>

<template>
  <div class="page">
    <!-- 全宽顶栏 -->
    <header class="topbar">
      <div class="topbar-inner">
        <a class="brand" href="/">
          <span class="brand-mark">♩</span>
          <span class="brand-name">灵谱</span>
          <span class="brand-sub">智能乐谱转录</span>
        </a>
        <nav class="nav">
          <button class="nav-item is-active">工作台</button>
          <button class="nav-item">我的乐谱</button>
          <button class="nav-item">帮助</button>
        </nav>
        <div class="topbar-right">
          <n-button secondary round class="pr-btn" @click="loadSample">示例乐谱</n-button>
          <n-button round type="primary" class="cta" @click="pickFile">上传 &amp; 转谱</n-button>
        </div>
      </div>
    </header>

    <main class="stage">
      <!-- 顶部宣传 / 上传条 -->
      <section
        class="hero card"
        :class="{ over: dragOver }"
        @drop="onDrop"
        @dragenter="onDragEnter"
        @dragover="onDragOver"
        @dragleave="onDragLeave"
      >
        <div class="hero-copy">
          <h1>把演奏，<span class="accent">写</span>成谱。</h1>
          <p class="hero-desc">上传你的钢琴音频，AI 帮你转成五线谱，跟播练习、节拍不丢。</p>

          <!-- 转谱进行中：进度反馈 -->
          <div v-if="transcribing" class="tran-status">
            <div class="tran-title">
              <span v-if="fileName" class="tran-file">{{ fileName }}</span>
              <span class="tran-msg">{{ transcribeMsg }}</span>
            </div>
            <n-progress
              type="line"
              :percentage="transcribePct"
              :show-indicator="false"
              :height="8"
              :border-radius="4"
              color="#c9a55e"
              rail-color="rgba(200,164,92,0.18)"
            />
          </div>

          <!-- 空闲：上传按钮区 -->
          <div v-else class="hero-actions">
            <input ref="fileInput" type="file"
              accept="audio/*,.musicxml,.xml,.gp,.gp5,.gpx,.alphatex,.txt" style="display:none"
              @change="onInputChange" />
            <n-button
              type="primary" round size="large" class="upload-btn"
              @click="pickFile"
            >＋ 选择音频上传</n-button>
            <n-button round size="large" quaternary @click="loadSample">载入示例乐谱</n-button>
          </div>

          <p class="hero-hint">支持拖拽音频到此处 · 也可上传 .txt / .alphatex 乐谱直接解析</p>
        </div>
        <div class="pipeline">
          <div class="pipe-line" aria-hidden="true">
            <span class="pipe-staff s1" /> <span class="pipe-staff s2" />
            <span class="pipe-staff s3" /> <span class="pipe-staff s4" />
            <span class="pipe-staff s5" />
          </div>
          <div v-for="(s, i) in steps" :key="s.no" class="pipe-step">
            <div class="pipe-note" :class="'n' + (i + 1)" aria-hidden="true">♫</div>
            <div class="pipe-no">{{ s.no }}</div>
            <div class="pipe-name">{{ s.name }}</div>
            <div class="pipe-desc">{{ s.desc }}</div>
          </div>
        </div>
      </section>

      <div class="workbench">
        <!-- 乐谱舞台 -->
        <section class="score-panel glass">
          <div class="panel-head">
            <div class="panel-title">
              <span class="dot" />
              {{ sheetStats ? sheetStats.title : '乐谱预览' }}
            </div>
            <div class="panel-actions">
              <n-tag v-if="sheetStats" size="small" :bordered="false" type="success">
                {{ sheetStats.tracks }} 轨 · {{ sheetStats.bars }} 小节
              </n-tag>
              <n-tag v-else-if="loadError" size="small" :bordered="false" type="error">加载失败</n-tag>
              <n-tag v-else size="small" :bordered="false">示例</n-tag>
              <n-button text size="small" @click="zoom(-1)">－ 缩小</n-button>
              <n-button text size="small" @click="zoom(1)">＋ 放大</n-button>
            </div>
          </div>
          <ScoreViewer
            ref="viewer"
            :initial-sheet="sampleMidiUrl"
            class="score-stage"
            @on-stats="onStats"
            @on-load-fail="loadError = $event"
            @on-time="onTime"
            @on-play-state="onPlayState"
          />
          <p v-if="loadError" class="score-err">{{ loadError }}</p>
        </section>

        <!-- 控制栏 -->
        <aside class="rail">
          <section class="panel glass rail-player">
            <div class="panel-head">
              <div class="panel-title"><span class="dot" />跟播播放</div>
            </div>
            <PlayerBar
              :duration="Math.max(1, (sheetStats?.durationMs || 0) / 1000)"
              :current="playTime"
              :playing="playing"
              :ready="playerReady"
              @toggle="togglePlay"
              @seek="seek"
              @speed="onSpeed"
              @loop="onLoop"
            />
          </section>

          <section class="panel glass rail-metro">
            <div class="panel-head">
              <div class="panel-title"><span class="dot" />节拍器</div>
              <span class="metro-beat">4/4</span>
            </div>
            <div class="metro-bpm">
              <span class="bpm-big">120</span><span class="bpm-unit">BPM</span>
            </div>
            <n-slider :value="120" :min="40" :max="208" :tooltip="false" />
            <div class="metro-sub">
              <n-tag size="small" :bordered="false">1/4</n-tag>
              <n-tag size="small" :bordered="false" type="success">强拍提醒</n-tag>
            </div>
          </section>
        </aside>
      </div>

      <footer class="foot">灵谱 · 面向钢琴演奏者的智能乐谱转录 demo</footer>
    </main>
  </div>
</template>

<style scoped>
.page {
  min-height: 100vh;
  background:
    radial-gradient(1200px 420px at 12% -8%, rgba(200, 164, 92, 0.16), transparent 60%),
    radial-gradient(1000px 420px at 88% -8%, rgba(94, 122, 90, 0.14), transparent 60%),
    var(--cream-0);
}

/* 顶栏 */
.topbar {
  position: sticky; top: 0; z-index: 20;
  height: var(--topbar-h);
  background: linear-gradient(180deg, #3a4f39, #2f3e30);
  box-shadow: 0 6px 18px -8px rgba(30, 40, 28, 0.5);
}
.topbar-inner {
  height: 100%; max-width: 1280px; margin: 0 auto; padding: 0 24px;
  display: flex; align-items: center; gap: 32px;
}
.brand { display: flex; align-items: center; gap: 10px; color: #f4eee0; }
.brand-mark {
  font-size: 30px; line-height: 1; color: var(--gold);
  display: grid; place-items: center; width: 40px; height: 40px;
  background: rgba(255, 255, 255, 0.08); border-radius: 12px;
}
.brand-name { font-size: 20px; font-weight: 700; letter-spacing: 1px; }
.brand-sub { font-size: 12px; color: rgba(244, 238, 224, 0.6); font-weight: 400; letter-spacing: 2px;
  border-left: 1px solid rgba(255,255,255,0.22); padding-left: 12px; }
.nav { display: flex; gap: 6px; margin-left: auto; }
.nav-item {
  border: 0; background: transparent; color: rgba(244, 238, 224, 0.72);
  padding: 8px 14px; border-radius: 8px; font-size: 14px; cursor: pointer; transition: all .2s;
}
.nav-item:hover { color: #fff; background: rgba(255,255,255,0.08); }
.nav-item.is-active { color: #fff; background: rgba(255,255,255,0.14); }
.topbar-right { display: flex; gap: 10px; }
.pr-btn { color: #f4eee0; border-color: rgba(255,255,255,0.28); }
.cta { background: var(--gold) !important; color: #3a2f14 !important; font-weight: 700; }

.stage { max-width: 1280px; margin: 0 auto; padding: 28px 24px 40px; }

.card {
  background: var(--paper); border-radius: var(--radius-lg);
  box-shadow: var(--shadow-soft); border: 1px solid var(--line);
}
.hero {
  display: grid; grid-template-columns: 0.95fr 1.05fr; gap: 28px; align-items: center;
  padding: 28px 30px; overflow: hidden; position: relative;
}
.hero::after {
  content: ''; position: absolute; right: -80px; bottom: -110px; width: 300px; height: 300px;
  background: radial-gradient(circle, rgba(94,122,90,0.14), transparent 65%);
}
.hero h1 { font-size: 34px; margin: 0 0 10px; color: var(--ink); letter-spacing: 1px; }
.hero .accent { color: var(--pine-600); font-style: italic; }
.hero-desc { color: var(--ink-faint); margin: 0 0 22px; font-size: 15px; line-height: 1.7; }
.hero-actions { display: flex; gap: 12px; flex-wrap: wrap; }
.upload-btn, .hero-actions :deep(.n-button) { cursor: pointer; }
.hero-hint { font-size: 12.5px; color: var(--ink-faint); margin: 18px 0 0; opacity: 0.8; }

/* 拖拽悬停反馈 */
.hero.over {
  border-color: var(--pine-600);
  box-shadow: 0 0 0 3px rgba(94, 122, 90, 0.22), var(--shadow-soft);
}
.hero.over .hero-desc { color: var(--pine-700); }

/* 转谱进度反馈 */
.tran-status {
  display: flex; flex-direction: column; gap: 14px; max-width: 420px;
  padding: 18px; border-radius: 14px;
  background: linear-gradient(135deg, rgba(200,164,92,0.10), rgba(94,122,90,0.08));
  border: 1px dashed var(--gold);
}
.tran-title { display: flex; flex-direction: column; gap: 3px; }
.tran-file { font-size: 14px; font-weight: 700; color: var(--ink); word-break: break-all; }
.tran-msg { font-size: 12.5px; color: var(--pine-700); }

/* —— 流水线：把"三个功能卡"改成有编排、带音阶感的步骤 —— */
.pipeline {
  position: relative; display: grid; grid-template-columns: repeat(3, 1fr);
  gap: 10px; padding: 26px 8px 10px;
}
.pipe-line {
  position: absolute; left: 8%; right: 8%; top: 74px;
  height: 100%; pointer-events: none; opacity: 1;
}
/* 贯穿音符的五线谱 */
.pipe-staff {
  position: absolute; left: 0; right: 0; height: 1.6px; background: #d9cdb2; border-radius: 2px;
}
.pipe-staff.s1 { top: 0; } .pipe-staff.s2 { top: 16px; }
.pipe-staff.s3 { top: 32px; } .pipe-staff.s4 { top: 48px; }
.pipe-staff.s5 { top: 64px; }

.pipe-step {
  position: relative; z-index: 1; text-align: center; padding: 6px 12px;
}
.pipe-note {
  width: 84px; height: 84px; margin: 0 auto 16px; border-radius: 50%;
  display: grid; place-items: center; font-size: 38px;
  background: var(--paper); color: var(--gold);
  border: 1px solid var(--wood-200);
  box-shadow: 0 10px 20px -10px rgba(80, 66, 42, 0.45);
  position: relative; z-index: 2;
}
.pipe-note.n1 { color: var(--pine-600); }
.pipe-note.n2 { color: var(--wood-600); }
.pipe-note.n3 { color: var(--gold); }
.pipe-no {
  font-family: Georgia, serif; font-size: 13px; letter-spacing: 3px;
  color: var(--ink-faint); margin-bottom: 6px;
}
.pipe-name { font-size: 17px; font-weight: 700; color: var(--ink-soft); margin-bottom: 6px; }
.pipe-desc { font-size: 12.5px; color: var(--ink-faint); line-height: 1.6; }

/* 工作台 */
.workbench {
  display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 20px; margin-top: 22px;
}
.glass {
  background: rgba(255, 255, 255, 0.82); backdrop-filter: blur(10px);
  border: 1px solid var(--line); border-radius: var(--radius-lg);
  box-shadow: var(--shadow-soft);
}
.panel { padding: 20px; }
.panel-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
.panel-title { display: flex; align-items: center; gap: 8px; font-weight: 700; color: var(--ink-soft); }
.panel-title .dot { width: 9px; height: 9px; border-radius: 50%; background: var(--gold); }
.panel-actions { display: flex; align-items: center; gap: 12px; }

.score-panel { min-width: 0; }
.score-stage {
  position: relative; min-height: 300px; border-radius: var(--radius-md);
  background: var(--paper);
  border: 1px dashed var(--wood-200);
  overflow: hidden;
  width: 100%;
}
.score-err { margin: 8px 4px 0; color: var(--error, #b4553f); font-size: 12.5px; }

.rail { display: flex; flex-direction: column; gap: 20px; }
.metro-beat { color: var(--pine-600); font-weight: 700; }
.metro-bpm { display: flex; align-items: baseline; gap: 6px; margin-bottom: 6px; }
.bpm-big { font-size: 44px; font-weight: 800; color: var(--ink); font-family: Georgia, serif; }
.bpm-unit { color: var(--ink-faint); letter-spacing: 1px; }
.metro-sub { display: flex; gap: 8px; margin-top: 14px; }

.foot { text-align: center; color: var(--ink-faint); font-size: 12px; padding-top: 30px; letter-spacing: 1px; }

@media (max-width: 900px) {
  .topbar-inner { flex-wrap: wrap; height: auto; padding: 12px 16px; gap: 14px; }
  .page { padding-top: 0; }
  .nav { order: 3; width: 100%; margin: 0; }
  .hero { grid-template-columns: 1fr; padding: 24px; }
  .workbench { grid-template-columns: 1fr; }
  .hero h1 { font-size: 26px; }
}
</style>