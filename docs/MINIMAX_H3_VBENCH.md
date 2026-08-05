# MiniMax H3 本地 T2V 测评

## 1. ComfyUI 环境

建议使用 ComfyUI `0.30.0` 或更高版本，并更新到包含 MiniMax H3 原生节点的版本。官方 T2V 工作流和模型下载说明见：

- https://docs.comfy.org/tutorials/video/minimax/minimax-h3
- https://huggingface.co/Comfy-Org/MiniMax-H3

将以下文件放到 ComfyUI 对应目录：

```text
models/diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors
models/text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors
models/vae/minimax_h3_video_vae_fp16.safetensors
models/vae/minimax_h3_audio_vae_fp32.safetensors
```

在 ComfyUI 模板库打开 `MiniMax H3 T2V`，确认单条视频可以生成后，使用 `Save (API Format)` 导出 API workflow，例如：

```text
workflows/comfyui/t2v/minimax_h3_t2v_api.json
```

## 2. 单卡建议

官方文档没有给出固定的最低显存。ComfyUI 的实际运行方式是动态显存卸载，因此建议按下面的档位准备：

| GPU 显存 | 建议 | 预期用途 |
|---|---|---|
| 12 GB | 可运行 | 480p 左右、5 秒、低并发；需要 32 GB 以上系统内存和高速 NVMe |
| 16–24 GB | 推荐起步 | 480p–720p、5 秒；更稳定，仍建议单任务 |
| 32–48 GB | 舒适 | 720p 及更长视频，减少 CPU/RAM 卸载 |
| 80 GB | 高吞吐 | 更高分辨率或多实例；仍要根据工作流实测 |

这些是工程建议，不是官方硬性门槛。H3 的压缩模型组合仍然很大：模型文件、视频 VAE、音频 VAE 和 Qwen3-VL 文本编码器会共同占用磁盘、显存和系统内存。建议至少准备：

- NVIDIA GPU，CUDA 驱动正常；一张卡即可，脚本按 ComfyUI 节点逐任务提交，不需要多卡并行。
- 系统内存 32 GB 起步，64 GB 更稳。
- NVMe 可用空间至少 100 GB；保守建议 150 GB 以上。
- 生成时保持 `--concurrency 1`，多 GPU 时启动多个 ComfyUI 服务端口，再通过 `--nodes` 分发任务。

## 3. 生成 VBench 视频

```bash
python3 pipelines/generate_minimax_h3_t2v.py \
  --cases runs/20260729_ltx23_t2v/cases/cases.json \
  --workflow workflows/comfyui/t2v/minimax_h3_t2v_api.json \
  --output-dir runs/20260729_minimax_h3_t2v/generation \
  --nodes http://127.0.0.1:8188 \
  --duration 5 \
  --width 1280 \
  --height 720 \
  --fps 24 \
  --concurrency 1 \
  --resume \
  --retries 1
```

H3 工作流通常是 24fps，时长会按 H3 的帧网格自动取整；因此这里记录 24fps，不要强行把工作流改成 25fps。H3 官方推荐的原生画布短边约 768 像素，分辨率应为 32 的倍数；如果显存不足，先改为 `864x480`。

输出结构与现有 T2V 流程一致：

```text
runs/20260729_minimax_h3_t2v/generation/<case_id>/
├── <case_id>.mp4
├── case.json
├── workflow.json
└── research_results.jsonl
```

## 4. 整理并评测

```bash
python3 pipelines/prepare_videos.py \
  --cases runs/20260729_ltx23_t2v/cases/cases.json \
  --generated-root runs/20260729_minimax_h3_t2v/generation \
  --video-root runs/20260729_minimax_h3_t2v/videos/prepared
```

之后将该 run 的 `config/run.yaml` 指向 `videos/prepared`，再执行现有的 `run_evaluation.py`。
