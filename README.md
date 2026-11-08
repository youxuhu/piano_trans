# 灵谱 · 钢琴音频转录工作台

面向纯钢琴独奏的本机单用户 Web 应用。音频上传后由独立 GPU 工作进程转录，生成保留演奏时序的 MIDI 和量化双手 MusicXML，并保存到本地曲库。浏览器提供曲库管理、原音试听、合成播放、倍速、A/B 循环和独立节拍器。

## 快速启动

已创建 `lingpu`（Python 3.11 / PyTorch 2.8.0+cu128）环境。本机 GPU 是 RTX 5090 D v2。系统需要 `ffmpeg` 和 `ffprobe`；前端需要 Node 22.12+（推荐 nvm 管理）。

```bash
# 项目根目录，首次安装；会创建环境、下载模型并安装前端依赖
bash scripts/setup.sh

# 日常启动：分别在两个终端执行
bash scripts/backend.sh
bash scripts/frontend.sh
```

打开 http://127.0.0.1:5173 。后端监听 `127.0.0.1:8000`；Vite 将 `/api` 转发给后端。不需要账户、云端服务或外部数据库。只运行一个后端实例、一个 Uvicorn worker。

如果环境已经存在，无需重复 setup：

```bash
conda activate lingpu
python backend/scripts/download_models.py  # 权重不存在时才需要
```

没有 conda shell 命令时，启动脚本会尝试 `$HOME/miniconda3/bin/conda`。前端脚本会尝试加载 `$HOME/.nvm/nvm.sh`。

### 环境与配置

`environment.yml` 描述基础环境，`backend/requirements.lock.txt` 是验证过的 Python 依赖快照。CUDA wheels 通过 PyTorch cu128 源安装；不要按旧项目的 Python 3.7 / PyTorch 1.4 环境安装。

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `LINGPU_DEVICE` | `cuda` | 可显式改为 `cpu`；GPU 失败不会静默回退 |
| `LINGPU_MODEL` | `bytedance` | 可配置 `transkun`，需准备独立环境及 CLI wrapper |
| `LINGPU_DATA_DIR` | `backend/data` | SQLite、原始音频和导出文件 |
| `LINGPU_WEIGHTS_DIR` | `backend/weights` | ByteDance 权重及校验 manifest |
| `TRANSKUN_EXECUTABLE` | PATH 中的 `transkun` | 独立环境 CLI 包装器绝对路径 |

模型只在工作进程启动时加载一次。下载脚本显式获取官方 Zenodo 权重，验证文件大小和官方 MD5，生成 SHA-256 manifest；启动时再验证本地 SHA-256。权重缺失或损坏时健康检查会显示未就绪，需修复后重启后端。

## 使用与边界

- 上传 WAV、MP3、M4A、OGG、FLAC、AAC、WEBM；上限 100 MB、10 分钟。推荐先用 10–30 秒纯钢琴片段验证效果。
- 转录参数支持自动/手动 BPM、拍号和量化精度。默认 4/4、十六分音符网格；左右手依据音域及连续性自动划分。
- 上传立刻返回任务 ID；进度来自实际解码、模型分段推理、建谱阶段。任务 ID 保存到浏览器，刷新后继续查询；曲库持久保存在后端。
- MIDI 保留音符秒级起止、力度和 CC64 踏板；MusicXML 用于可读排版，含和弦、多声部、休止和连音。左右手分配、BPM 与量化是启发式结果，复杂演奏仍需人工校对。
- 导入与阅读分为两个界面。MusicXML / MXL 会保存到曲库，刷新后仍可打开。阅读时可收起曲库，点击纸页左右两侧、左右滑动或使用方向键翻页，播放和拖动进度时跟随播放位置翻页。
- 每首曲目分别记住阅读小节、缩放和节拍器折叠状态；改变窗口或折叠工具后保留阅读位置。工具栏提供专注模式、全屏、适应宽度与适应整页。
- 合成播放以生成乐谱为准；原音播放按秒级时间轴带动乐谱光标。两种音源切换时保留时间位置，量化乐谱与自由速度演奏仍可能有偏差。双音轨乐谱支持左右手分别调节音量；练习面板可启用一小节预备拍，空格键播放/暂停。
- 机械节拍器支持 3/4、4/4、6/8，使用音频时钟提前调度声音，摆杆由同一时钟驱动。6/8 以附点四分音符为一拍，默认三细分；独立节拍器与乐谱播放器仍分别控制。
- 导出菜单提供打印 / 保存 PDF，会在新窗口按纸张宽度重新排版。中小屏幕底栏通过“更多”展开倍速与 A/B 控制。
- 音频转录曲目可从“视图与设置”重新建谱：调整 BPM、拍号、量化、双手分界和调号，无需重新推理。原始事件、原录音及首次导出文件保留；旧曲目首次重建时由现有 MIDI 恢复事件。成品 MusicXML 导入后保留原始记谱，不通过此接口重新量化。
- 音频转录曲目的“纠错”工作台支持谱面选音、增删、音高 / 时值 / 左右手修改及持久撤销 / 重做；局部重转录只推理所选音频及上下文，先预览再确认应用，版本检查防止覆盖新修改。用法与验证见 [音符纠错与局部重转录](docs/note-correction.md)。
- 不支持把包含人声和伴奏的混音自动改编成钢琴谱；不承诺立项书中尚未实测的精度、模型体积或实时性指标。

## 架构与接口

```text
Vue / Pinia / Naive UI / alphaTab
       │ multipart 上传、任务轮询、乐谱文件
FastAPI ── SQLite / 本地文件
       │ 队列（SQLite，单消费者）
独立推理进程：ffmpeg → ByteDance → 音符/踏板事件 → MIDI + MusicXML
```

后端 `backend/lingpu/` 中，`app.py` 管理 HTTP，`storage.py` 管理持久化，`worker.py` 串行执行任务，`audio.py` 解码，`models.py` 适配模型，`events.py` 定义中间表示，`score.py` 导出。

| 方法 | 路径 | 返回/用途 |
|---|---|---|
| POST | `/api/transcriptions` | multipart `audio`、可选 `bpm`、`time_signature`、`quantization`；202 `{task_id}` |
| GET | `/api/tasks/{id}` | 状态、阶段、百分比或 null、耗时、错误及 score_id |
| GET | `/api/scores` | 曲库数组 |
| GET | `/api/scores/{id}` | 曲目详情 |
| POST | `/api/scores/import` | multipart `file` 导入 MusicXML / MXL，201 返回曲目 |
| POST | `/api/scores/{id}/regenerate` | JSON 建谱参数；保留原始事件并重新导出 |
| PATCH | `/api/scores/{id}` | JSON `{title}` 重命名 |
| DELETE | `/api/scores/{id}` | 删除曲库记录及关联文件，204 |
| GET | `/api/scores/{id}/artifacts/{kind}` | `audio` / `midi` / `musicxml` |
| GET | `/api/health` | 存活、实际设备、模型状态、工作进程及 ready |

旧的同步 `/api/transcribe` 已退役。服务重启后将未完成任务标为失败，并清理解码临时文件；原始音频与已完成曲目保留。失败任务可在当前页面重新提交，刷新后需重新选择文件。

## 验证与评测

```bash
conda run -n lingpu python -m pytest -q
cd frontend
npm run typecheck
npm test
npm run build
# 浏览器回归：先在另一个终端 npm run dev -- --host 127.0.0.1 --port 5175
npm run test:browser
# 纠错回归默认端口 5176，也可设置 LINGPU_TEST_URL
npm run test:correction
```

运行检查与截图见 [验证记录](docs/verification.md)。模型基线、统一对比入口和实测结果见 [评测报告](docs/benchmark-report.md)。单模型命令需在项目根目录执行：

```bash
conda run -n lingpu python -m backend.scripts.benchmark 音源素材/your-file.mp3 \
  --model bytedance --device cuda --output-json /tmp/bytedance.json
# 若有同一演奏的真实参考 MIDI，可增加 --reference-midi /path/to/reference.mid
```

无参考 MIDI 的真实音频只报告耗时和事件数量，不计算或推测准确率。论文指标与本机验证结果分开记录。

新增的合成参考语料和识别 / 建谱分开评测见 [2026-11-06 验证记录](docs/iteration-2026-11-06.md)。首次运行浏览器测试需安装 Chromium（`npx playwright install chromium`）；测试会拦截 API，不会改动真实曲库。可用 `LINGPU_TEST_URL` 修改测试页面地址，`LINGPU_API_URL` 修改开发 / 预览代理目标。

## 来源与项目材料

- [ByteDance piano_transcription](https://github.com/bytedance/piano_transcription)：默认算法来源；仓库声明 Apache 2.0。
- [piano_transcription_inference](https://github.com/qiuqiangkong/piano_transcription_inference)：推理实现。
- [Zenodo 4034264](https://zenodo.org/records/4034264)：预训练权重，CC BY 4.0；使用与发表成果时需署名原作者。
- [Transkun](https://github.com/Yujia-Yan/Transkun)：对比模型。
- [Aria-AMT](https://github.com/EleutherAI/aria-amt)：后续研究候选，本轮未接入。
- `立项书.doc` 是立项目标；中期检查材料与运行验证记录分别维护，功能完成情况以代码、测试与评测报告为准。

重构前代码保存在 Git 基线提交 `e48db93`。模型、运行数据、node_modules 和 dist 均不纳入版本控制。
