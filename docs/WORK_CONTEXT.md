# VBench 工作上下文

更新时间：2026-07-30

本文用于下一个 work 恢复当前项目状态。

## 项目目标

项目统一管理 ComfyUI、Kling API 和直接上传的视频，并在 run 目录中完成 T2V/I2V 评测、日志和结果归档。

当前重点：

- T2V 使用 VBench-2.0。
- I2V 使用 VBench-i2v。
- 将 I2V 中只依赖视频、不需要输入图片的指标复用到 T2V。
- 评测阶段使用本地权重，禁止联网下载。

## 环境

本地 Mac 项目目录：

~~~
/Users/zhouruomiao/Documents/VBench
~~~

服务器 Docker 工作目录：

~~~
/workspace
~~~

服务器代码目录通常为：

~~~
/workspace/VBench-repo
~~~

评测代码：

~~~
/workspace/source/VBench-2.0
/workspace/source/vbench
/workspace/source/vbench2_beta_i2v
~~~

服务器 Python/运行时：

~~~
/opt/conda/bin/python
Python 3.11
PyTorch 2.7.1+cu126
CUDA 12.6
GPU 显存约 44 GiB
~~~

服务器无法稳定直连 GitHub/Hugging Face，因此模型应在联网环境下载后上传，评测时使用 offline 模式。

## 缓存路径

统一环境脚本：

~~~
scripts/vbench_env.sh
~~~

默认路径：

~~~
/root/.cache/huggingface/       # Hugging Face 模型，例如 SigLIP
/root/.cache/vbench2/           # T2V/VBench-2.0 权重
/root/.cache/vbench/            # I2V/VBench 权重
/root/.cache/vbench2/torch/     # T2V Torch Hub 权重
/root/.cache/vbench/torch/      # I2V Torch Hub 权重
~~~

关键变量：

~~~
HF_HOME=/root/.cache/huggingface
VBENCH2_CACHE_DIR=/root/.cache/vbench2
VBENCH_CACHE_DIR=/root/.cache/vbench
TORCH_HOME=/root/.cache/vbench2/torch
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
HF_DATASETS_OFFLINE=1
~~~

run_t2v_evaluation.sh 会加载 vbench_env.sh，覆盖旧缓存变量，避免 Shell 中残留路径造成模型找不到。需要换根目录时使用 VBENCH_CACHE_ROOT。

## 主要权重

T2V/VBench-2.0：

~~~
/root/.cache/vbench2/lmms-lab/LLaVA-Video-7B-Qwen2
/root/.cache/vbench2/Qwen/Qwen2.5-7B-Instruct
/root/.cache/vbench2/arcface/resnet18_110.pth
/root/.cache/vbench2/torch/checkpoints/retinaface_resnet50_2020-07-20-f168fae3c.zip
/root/.cache/vbench2/torch/hub/checkpoints/cotracker2.pth
~~~

LLaVA 依赖 SigLIP：

~~~
/root/.cache/huggingface/hub/models--google--siglip-so400m-patch14-384/
~~~

其中 model.safetensors 必须约 3.5GB；4KB 文件或断开的符号链接不算完成。

I2V/VBench：

~~~
/root/.cache/vbench/dino_model/
/root/.cache/vbench/dreamsim_ckpts/
/root/.cache/vbench/clip_model/
/root/.cache/vbench/aesthetic_model/
/root/.cache/vbench/pyiqa_model/
/root/.cache/vbench/amt_model/
/root/.cache/vbench/raft_model/
/root/.cache/vbench/torch/hub/checkpoints/cotracker2.pth
~~~

## Run 目录

T2V：

~~~
runs/<run_id>/
├── config/run.yaml
├── cases/cases.json
├── cases/selected_full_info.json
├── generation/<case_id>/<case_id>.mp4
├── generation/manifest.jsonl
├── videos/prepared/<dimension>/*.mp4
└── evaluation/<dimension>/
~~~

I2V：

~~~
runs/<run_id>/
├── config/run.yaml
├── cases/cases.json
├── cases/images/
├── generation/
├── videos/prepared/*.mp4
└── evaluation/<dimension>/
~~~

T2V 按维度整理视频；I2V 使用公共视频目录和输入图片目录。

## 生成和准备脚本

T2V ComfyUI：

~~~
pipelines/generate_t2v_batch.py
pipelines/generate_t2v_single.py
configs/generation/ltx23_t2v.yaml
configs/generation/wan22_t2v.yaml
~~~

Kling：

~~~
pipelines/kling_generate_t2v.py
~~~

视频整理：

~~~
pipelines/prepare_videos.py
~~~

Kling 常只有 -0.mp4，标准 metadata 可能要求 -1.mp4、-2.mp4，对应 run 配置需设置：

~~~
skip_missing_videos: true
~~~

## 评测入口

T2V 一键入口：

~~~
scripts/run_t2v_evaluation.sh
~~~

流程为：生成 manifest、整理视频、检查模型、按 run.yaml 顺序评测。当前暂时不执行分辨率/帧率/时长预检查，因为不同生成模型输出规格可能不同。

~~~
bash scripts/run_t2v_evaluation.sh /workspace/runs/<run_id>
bash scripts/run_t2v_evaluation.sh /workspace/runs/<run_id> --resume
~~~

I2V 单指标入口：

~~~
pipelines/run_i2v_evaluation.py
~~~

## 已完成和暂缓指标

T2V 已调试：

~~~
Motion_Rationality
Mechanics
Human_Identity
Motion_Order_Understanding
Complex_Plot
Multi-View_Consistency
~~~

Human_Anatomy 暂缓，原因是当前 PyTorch/CUDA 与 MMCV/MMDetection 版本不兼容。

I2V 已完成或验证：

~~~
i2v_subject
i2v_background
subject_consistency
background_consistency
aesthetic_quality
imaging_quality
temporal_flickering
motion_smoothness
dynamic_degree
~~~

camera_motion 需要专用镜头运动标签数据，普通 I2V 视频不能直接用于该指标。

## T2V 复用视频-only 指标

以下 7 个指标只读取视频帧，不需要输入图片：

~~~
subject_consistency
background_consistency
aesthetic_quality
imaging_quality
temporal_flickering
motion_smoothness
dynamic_degree
~~~

适配器：

~~~
pipelines/run_video_only_evaluation.py
~~~

run.yaml 配置：

~~~
video_only_dimensions:
  - subject_consistency
  - background_consistency
  - aesthetic_quality
  - imaging_quality
  - temporal_flickering
  - motion_smoothness
  - dynamic_degree
video_only_videos_path: videos/prepared
~~~

这些指标从视频文件名解析 prompt，不使用 selected_full_info.json 和输入图片。

## 近期代码改动

- T2V LLaVA 视频采样默认统一为 32 帧。
- Complex_Plot 增加显存释放，并修复重复释放 video 的 UnboundLocalError。
- vbench2.utils.save_json 支持 NumPy scalar 和 Path。
- check_models.py 增加权重检查和视频-only 指标检查。
- run_evaluation.py 支持普通 T2V 指标和视频-only 指标混合调度。
- build_t2v_cases.py 会自动生成基础 run.yaml 并写入视频-only 配置。
- run_t2v_evaluation.sh 会设置离线环境，不会在评测过程中从 Hugging Face 下载。

## 下一个 work 建议

1. 将最新 pipelines、scripts 和 source 同步到服务器。
2. 检查服务器 run.yaml 是否包含 video_only_dimensions 和 video_only_videos_path。
3. 先单独 smoke test temporal_flickering 或 subject_consistency。
4. 再运行完整 T2V 一键评测。
5. 检查 evaluation/dispatch_results.json、evaluation/evaluation.log 和各指标结果。
6. 最后再决定是否继续适配 camera_motion 或 Human_Anatomy。
