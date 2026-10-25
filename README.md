# 灵谱 —— 面向钢琴演奏用户的智能乐谱转录应用（Demo）

校级立项项目。Web 应用，跑通「上传音频 → 转录出乐谱 → 可视化渲染 → 跟播播放 + 节拍器」完整主流程。

## 技术栈

- **前端**：Vue 3 + Vite + Naive UI + Pinia + alphaTab（MusicXML 五线谱渲染与播放）
- **后端**：Python FastAPI，转谱用 **Basic Pitch**（onnxruntime 推理），音乐建谱用 music21
- **音频解码**：ffmpeg（已内嵌 `backend/ffmpeg.exe` 与 `ffprobe.exe`，无需额外安装）

整体是前后端分离：前端 SPA 通过 Vite proxy 把 `/api` 代理到后端。

## 目录结构

```
大创/
├─ frontend/                 # Vue 3 + Vite 前端
│  ├─ src/
│  │  ├─ components/         # ScoreViewer / PlayerBar 等
│  │  ├─ services/transcribe.js  # 前端调后端转谱的统一入口
│  │  ├─ samples/sampleSheet.js  # 预置示例乐谱
│  │  ├─ styles/             # global.css / theme.js（主题变量）
│  │  └─ views/HomeView.vue
│  └─ package.json
├─ backend/                  # FastAPI 后端
│  ├─ main.py                # 入口：/api/transcribe + /api/health
│  ├─ ffmpeg.exe / ffprobe.exe   # 内嵌音频解码器
│  ├─ midi_to_alphatex.py    # ⚠️ 早期 AlphaTex 方案的遗留，当前 main.py 未接入
│  ├─ output/                # 转录产物（.mid / .musicxml，调试用）
│  └─ samples/ weights/      # 预留空目录
├─ 音源素材/                 # 测试音频
├─ 立项书.doc / 调查.md / 软件设计.md
└─ README.md
```

## 环境搭建

### 后端（conda）

本项目后端依赖都在 conda 环境里。推荐新建或复用环境后装本仓库锁定的依赖：

```bash
# 方式一：用 requirements.txt 装（推荐）
conda create -n lingpu python=3.10 -y
conda activate lingpu
pip install -r backend/requirements.txt
```

> 说明：`basic-pitch` 的权重由包自带，通过 onnxruntime 推理，**不依赖** `软件设计.md` 里提到的 171MB checkpoint。「音源素材」目录下的 mp3 需要 ffmpeg 解码，本项目已把 `backend/ffmpeg.exe` / `ffprobe.exe` 打包在仓库里，librosa 会自动找到同目录的可执行文件。

### 前端（Node）

```bash
cd frontend
npm install
```

需要 Node 18+。

## 运行

开两个终端，分别起前后端。

```bash
# 终端 1 —— 后端（默认 8000 端口）
conda activate lingpu
python -m uvicorn main:app --host 127.0.0.1 --port 8000    # 需在 backend/ 下运行
```

```bash
# 终端 2 —— 前端（默认 5173 端口）
cd frontend
npm run dev
```

浏览器打开 Vite 提示的地址（通常是 `http://localhost:5173`）。

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/transcribe` | 上传音频（multipart `audio` 字段），返回 MusicXML 二进制流。支持 wav/mp3/m4a/ogg/flac/aac/webm |
| GET | `/api/health` | 健康检查，返回 `{status, model_loaded, device}` |

转谱是**同步**请求：Basic Pitch 在 CPU 上推理约 30s / 10s 音频，长音频会比较慢，演示建议用 ≤30s 片段。

## 已知问题 / 注意事项

- **转谱链路**：音频 → Basic Pitch → pretty_midi 音符事件 → music21 直接建谱 → MusicXML。**不经过 MIDI 文件解析**（music21 会把 pretty_midi 的 220tpb MIDI 时序读塌缩，详见 `main.py` 顶部注释）。
- **单声部优先**：Basic Pitch 常在同一时刻报出基音 + 五度/泛音，后端按置信度只保留主导音，所以是多音和弦曲子的转录会偏单音旋律。
- **MusicXML 补全**：music21 默认只在第一个 measure 写 `<attributes>`，而 alphaTab v1.8.4 要求每个 measure 都显式带，后端在返回前用正则把 attributes 块复制到所有小节（`main.py` 里 `_ensure_attrs_every_measure`）。
- **`midi_to_alphatex.py`**：早期「音频 → AlphaTex」方案的转换器，当前 `main.py` 已改走 MusicXML，此文件未接入正式链路，可保留作参考或删除。
- **CORS**：后端已放开允许跨域，vite dev 端口 5173/5174 可用。