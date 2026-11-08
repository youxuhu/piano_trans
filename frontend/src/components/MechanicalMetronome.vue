<script setup lang="ts">
import { NSelect, NSlider } from 'naive-ui'
import type { BeatSettings } from '../services/beatClock'
const metro = defineModel<BeatSettings & { enabled: boolean }>({ required: true })
const metroCollapsed = defineModel<boolean>('collapsed', { default: false })
defineProps<{ angle: number; beat: number }>()
const emit = defineEmits<{ change: [] }>()
function changeMetro() {
  emit('change')
}
function changeMeter() {
  metro.value.subdivisions = metro.value.meter === '6/8' ? 3 : 1
  emit('change')
}
function toggleMetro() {
  metro.value.enabled = !metro.value.enabled
  emit('change')
}
function adjustMetro(delta: number) {
  metro.value.bpm = Math.max(40, Math.min(220, metro.value.bpm + delta))
  emit('change')
}
</script>
<template>
  <aside class="practice-tools" :class="{ collapsed: metroCollapsed }">
    <section class="setting-card metronome-card">
      <div class="metro-header">
        <button
          class="metro-collapse"
          :aria-expanded="!metroCollapsed"
          :aria-label="metroCollapsed ? '展开节拍器' : '收起节拍器'"
          @click="metroCollapsed = !metroCollapsed"
        >
          <span class="metro-heading"><i :class="{ active: metro.enabled }" />节拍器</span
          ><span aria-hidden="true">{{ metroCollapsed ? '‹' : '›' }}</span>
        </button>
      </div>
      <template v-if="!metroCollapsed">
        <div class="setting-row">
          <span>拍号</span
          ><n-select
            v-model:value="metro.meter"
            size="small"
            :options="[
              { label: '3/4', value: '3/4' },
              { label: '4/4', value: '4/4' },
              { label: '6/8', value: '6/8' },
            ]"
            @update:value="changeMeter"
          />
        </div>
        <div class="mechanical-metro">
          <div class="metro-body" :aria-label="`机械节拍器，${metro.bpm} BPM`">
            <div class="metro-shell" />
            <div class="metro-face">
              <div class="metro-scale">
                <span><b>Largo</b><small>40</small></span>
                <span><b>Larghetto</b><small>60</small></span>
                <span><b>Andante</b><small>80</small></span>
                <span><b>Moderato</b><small>100</small></span>
                <span><b>Allegro</b><small>120</small></span>
                <span><b>Vivace</b><small>144</small></span>
                <span><b>Presto</b><small>176</small></span>
                <span><b>Prestissimo</b><small>208</small></span>
              </div>
            </div>
            <div class="metro-pendulum" :style="{ transform: `rotate(${angle}deg)` }">
              <div
                class="metro-weight"
                :style="{ bottom: `${22 + ((220 - metro.bpm) / 180) * 50}%` }"
              />
            </div>
            <div class="metro-pivot" />
            <div class="metro-base" />
            <button
              class="metro-play"
              :aria-label="metro.enabled ? '暂停节拍器' : '启动节拍器'"
              :title="metro.enabled ? '暂停节拍器' : '启动节拍器'"
              @click="toggleMetro"
            >
              <span v-if="metro.enabled" class="pause-symbol" /><span v-else class="play-symbol" />
            </button>
          </div>
        </div>
        <div class="metro-caption">
          {{ metro.meter === '6/8' ? '附点四分音符' : '四分音符' }} ·
          {{ beat ? `第 ${beat} 拍` : '独立节拍' }}
        </div>
        <div class="metronome-bpm">
          <button
            class="tempo-step"
            aria-label="减慢速度"
            :disabled="metro.bpm <= 40"
            @click="adjustMetro(-1)"
          >
            −
          </button>
          <div class="tempo-value">
            <strong>{{ metro.bpm }}</strong
            ><span>BPM</span>
          </div>
          <button
            class="tempo-step"
            aria-label="加快速度"
            :disabled="metro.bpm >= 220"
            @click="adjustMetro(1)"
          >
            ＋
          </button>
        </div>
        <n-slider
          v-model:value="metro.bpm"
          :min="40"
          :max="220"
          :step="1"
          @update:value="changeMetro"
        />
        <div class="setting-row">
          <span>细分</span
          ><n-select
            v-model:value="metro.subdivisions"
            size="small"
            :options="[
              { label: '四分音符', value: 1 },
              { label: '八分音符', value: 2 },
              { label: '三连音', value: 3 },
              { label: '十六分音符', value: 4 },
            ]"
            @update:value="changeMetro"
          />
        </div>
      </template>
    </section>
  </aside>
</template>
<style scoped>
.practice-tools {
  display: flex;
  align-self: start;
  justify-content: flex-end;
}

.practice-tools .setting-card {
  width: 100%;
  padding: 14px;
}

.collapsed .metronome-card {
  padding: 9px 5px;
}
.metro-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}
.metro-collapse {
  display: flex;
  flex: 1;
  align-items: center;
  justify-content: space-between;
  gap: 4px;
  padding: 2px 0;
  border: 0;
  background: transparent;
  color: #243747;
  font-weight: 650;
  font-size: 12px;
  cursor: pointer;
}
.metro-collapse span:last-child {
  color: #738b89;
  font-size: 19px;
  line-height: 1;
}
.collapsed .metro-collapse {
  flex-direction: column;
  gap: 5px;
  font-size: 11px;
}
.metro-heading {
  display: inline-flex;
  align-items: center;
  gap: 7px;
}
.metro-heading i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #c7d4d1;
}
.metro-heading i.active {
  background: #328d77;
  box-shadow: 0 0 0 3px #d9eee8;
}
.collapsed .metro-heading {
  flex-direction: column;
  gap: 5px;
}
.mechanical-metro {
  display: flex;
  justify-content: center;
  margin: 15px auto 12px;
}
.metro-body {
  position: relative;
  width: 190px;
  height: 270px;
  filter: drop-shadow(0 7px 5px #344d432d);
}
.metro-shell {
  position: absolute;
  inset: 0;
  clip-path: polygon(43% 0, 57% 0, 66% 4%, 100% 96%, 96% 100%, 4% 100%, 0 96%, 34% 4%);
  background:
    repeating-linear-gradient(88deg, #ffffff06 0 1px, #130b080d 2px 3px, transparent 4px 8px),
    linear-gradient(95deg, #492a1b, #9e704c 16%, #62402c 33%, #a17450 52%, #69442d 75%, #4c2e20);
  box-shadow: inset 0 0 0 3px #583725;
}
.metro-face {
  position: absolute;
  inset: 16px 29px 55px;
  clip-path: polygon(36% 0, 64% 0, 100% 100%, 0 100%);
  background: linear-gradient(90deg, #201c19, #44362c 48%, #191715);
  box-shadow: inset 0 0 10px #000;
}
.metro-scale {
  position: absolute;
  inset: 5px 31px 4px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  align-items: center;
  padding: 4px 0;
  background: linear-gradient(90deg, #d0c4a6, #f5ecd9 23%, #ede2c9 76%, #c9b998);
  color: #5e5241;
  font:
    9px Georgia,
    serif;
  box-shadow: 0 1px 3px #0008;
}
.metro-scale span {
  width: 100%;
  display: flex;
  flex-direction: column;
  text-align: center;
  border-bottom: 1px solid #9e927d80;
  line-height: 1.05;
}
.metro-scale b {
  font-size: 9px;
  font-weight: 600;
}
.metro-scale small {
  font-size: 8px;
}
.metro-pendulum {
  position: absolute;
  z-index: 2;
  bottom: 55px;
  left: calc(50% - 2px);
  width: 4px;
  height: 194px;
  border-radius: 3px;
  background: linear-gradient(90deg, #696b68, #f5f4e9, #848680);
  box-shadow: 1px 1px 2px #0008;
  transform: rotate(18deg);
  transform-origin: 50% 100%;
}
.metro-weight {
  position: absolute;
  left: -6px;
  width: 16px;
  height: 15px;
  border-radius: 2px;
  background: linear-gradient(90deg, #84632d, #e1c589 35%, #ae8b4e 80%, #755628);
  box-shadow: 0 2px 3px #0009;
}
.metro-weight::after {
  content: '';
  position: absolute;
  inset: 3px 0 auto;
  border-top: 1px solid #f3dca580;
}
.metro-pivot {
  position: absolute;
  z-index: 3;
  bottom: 51px;
  left: calc(50% - 5px);
  width: 10px;
  height: 10px;
  border: 2px solid #a38c69;
  border-radius: 50%;
  background: #39332b;
}
.metro-base {
  position: absolute;
  right: 2px;
  bottom: 0;
  left: 2px;
  height: 51px;
  clip-path: polygon(3% 0, 97% 0, 100% 91%, 97% 100%, 3% 100%, 0 91%);
  border-top: 1px solid #be906a;
  background:
    repeating-linear-gradient(87deg, #ffffff05 0 1px, #0000000c 2px 3px, transparent 4px 9px),
    linear-gradient(90deg, #543321, #a16e49 28%, #805237 55%, #50301f);
}
.metro-play {
  position: absolute;
  z-index: 4;
  bottom: 9px;
  left: calc(50% - 16px);
  display: grid;
  width: 32px;
  height: 32px;
  place-items: center;
  border: 1px solid #e2c799;
  border-radius: 50%;
  background: linear-gradient(145deg, #b69462, #795735);
  box-shadow: 0 1px 4px #0008;
  cursor: pointer;
}
.metro-play:hover {
  background: linear-gradient(145deg, #d3b585, #987448);
}
.play-symbol {
  width: 0;
  height: 0;
  margin-left: 2px;
  border-top: 6px solid transparent;
  border-bottom: 6px solid transparent;
  border-left: 9px solid #fff;
}
.pause-symbol {
  width: 9px;
  height: 11px;
  border-right: 3px solid #fff;
  border-left: 3px solid #fff;
}
@media (prefers-reduced-motion: reduce) {
  .metro-pendulum {
    transform: rotate(18deg) !important;
  }
}

.metronome-bpm {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 5px;
  padding: 7px;
  border: 1px solid #e6eeeb;
  border-radius: 12px;
  background: #f8fbfa;
}

.tempo-value {
  display: flex;
  align-items: baseline;
  justify-content: center;
  gap: 5px;
}
.tempo-step {
  display: grid;
  width: 29px;
  height: 29px;
  flex: none;
  place-items: center;
  border: 1px solid #dce8e4;
  border-radius: 9px;
  background: #fff;
  color: #456963;
  font-size: 17px;
  cursor: pointer;
}
.tempo-step:hover:not(:disabled) {
  background: #eaf5f1;
}
.tempo-step:disabled {
  opacity: 0.35;
  cursor: default;
}

.metronome-bpm strong {
  font-size: 24px;
  font-weight: 650;
}

.metronome-bpm span {
  color: #8b9aa2;
  font-size: 10px;
}

.metro-caption {
  color: #7b766b;
  text-align: center;
  font:
    11px Georgia,
    serif;
  margin: -4px 0 10px;
}
.practice-tools {
  width: 100%;
}
.setting-card {
  border: 1px solid #e2e9ed;
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 3px 14px #253b4708;
}
.setting-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-top: 12px;
  color: #7d9099;
  font-size: 11px;
}
.setting-row :deep(.n-select) {
  width: 140px;
}
@media (max-width: 900px) {
  .metro-body {
    zoom: 0.85;
  }
}
@media (max-width: 680px) {
  .metro-body {
    zoom: 0.6;
  }
  .setting-row {
    flex-wrap: wrap;
  }
}
</style>
