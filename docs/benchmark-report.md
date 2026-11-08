# 灵谱转录模型实测记录

**运行日期：** 2026-10-25  
**音源：** `音源素材/小星星_爱给网_aigei_com.mp3`，截取开头 10 秒，转为单声道 22,050 Hz WAV。  
**硬件：** NVIDIA GeForce RTX 5090 D v2；CUDA 12.8；PyTorch 2.8.0+cu128。  
**模型：** ByteDance `piano_transcription_inference` 与 Transkun 2.0.1。两者使用同一 WAV 和 CUDA 设备。

## 实测结果

| 模型 | 输出音符数 | 踏板区间数 | 模型加载 | 端到端时间 | 峰值显存 |
| --- | ---: | ---: | ---: | ---: | --- |
| ByteDance | 19 | 4 | 2.814 s | 3.679 s | 356,644,352 bytes |
| Transkun | 18 | 3 | 仅 parent adapter 初始化 | 11.322 s | 未采集 |

计时为本机的一次实跑记录。ByteDance 的端到端时间是模型加载加转录；Transkun 由独立 conda 子进程运行，端到端时间包括子进程启动、模型加载和转录，适配器无法将这些阶段拆开。Transkun 的 CUDA 子进程显存不在父进程 PyTorch 计数器内，因此不报告显存值。

这段 MP3 没有配套 MIDI 参考标注，所以本次只比较运行时间和输出事件数量，**不计算或推断 F1、音符准确率或模型优劣**。不同模型的事件数不同只代表本次输出数量不同。

## 复现

Transkun 使用独立环境，安装 CLI 及兼容旧 `pkg_resources` 的 setuptools 版本：

```bash
conda run -n lingpu-transkun pip install -r scripts/transkun-requirements.txt
```

完整重跑（会重建 `/tmp/lingpu-benchmark.wav` 并输出逐模型 JSON 与汇总 JSON）：

```bash
conda run -n lingpu python backend/scripts/benchmark_suite.py --device cuda
```

生成的原始测量结果位于 `backend/output/benchmarks/transkun.json`、`backend/output/benchmarks/bytedance.json` 和 `backend/output/benchmarks/suite.json`。Transkun wrapper 位于 `scripts/transkun.sh`。

用于版本留存的摘要见 [benchmark-results.json](benchmark-results.json)。这里的模型流水线时间排除音频解码和顶层 Python 启动；新版基准脚本使用 `model_pipeline_seconds` 字段表达相同计时范围。该单片段计时只用于验证环境与流程，不代表完整性能基准。

首次准备隔离环境可以执行：

```bash
conda create -n lingpu-transkun --clone lingpu -y
conda run -n lingpu-transkun pip install -r scripts/transkun-requirements.txt
```

转录服务默认继续使用 ByteDance；对比应在无其他 GPU 推理任务时串行执行。
