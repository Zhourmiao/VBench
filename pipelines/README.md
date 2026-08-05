# 统一评测入口

`run_evaluation.py` 是项目级评测入口，应从项目根目录执行，而不是从 `evaluation/` 输出目录执行。

## 生成 VBench-2.0 T2V cases

使用 benchmark 当前目录中的精选 11 个维度：

```bash
python pipelines/build_t2v_cases.py \
  --output-dir runs/<run_id>/cases
```

生成全部官方维度：

```bash
python pipelines/build_t2v_cases.py \
  --all-dimensions \
  --output-dir runs/<run_id>/cases
```

脚本默认读取 `benchmarks/vbench2_t2v/manifest.json`、`full_info.json`、`prompts/` 和中文 prompt 目录，并按照 manifest 中的样本数生成 `cases.json` 与 `selected_full_info.json`。可用 `--dimensions`、`--samples-per-prompt`、`--diversity-samples-per-prompt` 覆盖默认选择。

## T2V 端到端生成步骤（ComfyUI）

以下示例在 Mac 本地提交 ComfyUI 任务，并使用英文评测 prompt。将 `<workflow.json>` 替换为 ComfyUI 导出的 API 格式 workflow。

### 1. 创建 run 目录

```bash
cd /Users/zhouruomiao/Documents/VBench

export RUN_ID=20260729_ltx23_t2v_7x5
export RUN_DIR=/Users/zhouruomiao/Documents/VBench/runs/$RUN_ID

mkdir -p "$RUN_DIR"/{config,cases,generation,videos/prepared,evaluation}
```

### 2. 生成 cases.json

```bash
python3 pipelines/build_t2v_cases.py \
  --output-dir "$RUN_DIR/cases" \
  --dimensions \
    Human_Identity \
    Mechanics \
    Motion_Order_Understanding \
    Motion_Rationality \
    Multi-View_Consistency \
    Complex_Plot \
  --video-root videos/prepared \
  --duration 5 \
  --fps 25 \
  --width 1280 \
  --height 720
```

输出：

```text
$RUN_DIR/cases/cases.json
$RUN_DIR/cases/selected_full_info.json
$RUN_DIR/config/run.yaml
```

`build_t2v_cases.py` 会在 run 目录缺少配置时自动创建 `config/run.yaml`；如果配置已经存在，则不会覆盖已有配置。

已有 run 追加 prompt 时使用 `--append`。脚本会按“维度 + 英文 prompt + sample_index”复用旧 case，保持旧 `case_id` 不变，只为新增 prompt 追加新的 case；已有配置中的维度列表也会同步更新：

```bash
python pipelines/build_t2v_cases.py \
  --output-dir runs/<run_id>/cases \
  --append
```

随后使用生成脚本的 `--resume`，旧视频会跳过，只生成新增 case。

### 3. 检查 ComfyUI 节点

```bash
curl --max-time 10 http://110.126.0.52:8181/system_stats
curl --max-time 10 http://110.126.0.52:8182/system_stats
```

两个节点都返回 JSON 后再提交批量任务。如果使用其他 ComfyUI 地址，替换 `--nodes` 参数。

### 4. 调用 ComfyUI 批量生成

推荐使用工作流配置文件，避免把节点映射全部写在命令行中：

```bash
python3 -u pipelines/generate_t2v_batch.py \
  --cases "$RUN_DIR/cases/cases.json" \
  --generation-config configs/generation/wan22_t2v.yaml \
  --output-dir "$RUN_DIR/generation" \
  --resume \
  --retries 1 \
  --retry-delay 10
```

切换到 LTX-2.3 时只需要替换配置：

```bash
--generation-config configs/generation/ltx23_t2v.yaml
```

配置文件集中保存 workflow 路径、ComfyUI 节点、prompt/seed/尺寸/FPS/时长字段映射和默认生成参数。命令行仍可覆盖配置中的同名参数。

Wan 工作流的关键节点说明：

```text
正向 prompt：89.text
负向 prompt：72.text
seed：81.noise_seed、78.noise_seed
宽度：74.width
高度：74.height
FPS：88.fps
视频帧数：74.length
```

配置文件中的 Wan 默认参数为：

```yaml
duration: 10
fps: 25
duration_scale: 25
duration_offset: 1
```

因此 10 秒视频会写入：

```text
length = 10 × 25 + 1 = 251 帧
```

```bash
python3 -u pipelines/generate_t2v_batch.py \
  --cases "$RUN_DIR/cases/cases.json" \
  --template /Users/zhouruomiao/Documents/VBench/workflows/ltx23_t2v_api.json \
  --output-dir "$RUN_DIR/generation" \
  --nodes \
    http://110.126.0.52:8181 \
    http://110.126.0.52:8182 \
  --prompt-field prompt_eval_en \
  --concurrency 2 \
  --resume \
  --retries 1 \
  --retry-delay 10
```

`--prompt-field prompt_eval_en` 表示使用英文 prompt，不使用 `prompt_input` 中的中文 prompt。`--resume` 会跳过已经存在的非空视频。

每个 case 的输出结构：

```text
$RUN_DIR/generation/<case_id>/
├── <case_id>.mp4
├── case.json
├── workflow.json
└── research_results.jsonl
```

批量结果：

```text
$RUN_DIR/generation/batch_results.json
$RUN_DIR/generation/batch_timing.json
```

### 5. 生成完成后的整理与评测

```bash
python3 -u pipelines/preflight_videos.py \
  --run-dir "$RUN_DIR" \
  --stage generation

python3 -u pipelines/build_generation_manifest.py \
  --run-dir "$RUN_DIR" \
  --benchmark vbench2 \
  --hash

python3 -u pipelines/prepare_videos.py \
  --cases "$RUN_DIR/cases/cases.json" \
  --generated-root "$RUN_DIR/generation" \
  --video-root "$RUN_DIR/videos/prepared"

python3 -u pipelines/check_models.py \
  --run-dir "$RUN_DIR"
```

以上检查通过后，先运行单指标 smoke test，再使用 `run_evaluation.py` 批量评测。

## Kling API 批量生成 T2V

Kling 使用与 ComfyUI 相同格式的 `cases.json`，默认读取其中的英文字段 `prompt_eval_en`。建议为 Kling 单独创建 run 目录，避免覆盖 ComfyUI 生成结果。

### 1. 设置 Kling API Key

```bash
export KLING_API_KEY="你的_Kling_API_Key"
```

也可以使用 access key 和 secret key：

```bash
export KLING_ACCESS_KEY="你的_Access_Key"
export KLING_SECRET_KEY="你的_Secret_Key"
```

### 2. 启动批量生成

```bash
python3 -u pipelines/kling_generate_t2v.py \
  --cases "$RUN_DIR/cases/cases.json" \
  --output-root "$RUN_DIR/generation" \
  --model kling-3.0-turbo \
  --duration 5 \
  --aspect-ratio 16:9 \
  --poll-interval 10 \
  --timeout 900 \
  2>&1 | tee "$RUN_DIR/generation/kling_generation.log"
```

Kling 当前不支持像 ComfyUI 一样通过 seed 固定随机结果。`cases.json` 中的 seed 会被保留到元数据中，但不会传给 Kling API。

生成结果：

```text
$RUN_DIR/generation/<case_id>/<case_id>.mp4
$RUN_DIR/generation/<case_id>/case.json
$RUN_DIR/generation/<case_id>/generation.json
$RUN_DIR/generation/manifest.jsonl
$RUN_DIR/generation/kling_generation.log
```

如果某个 case 已经存在非空视频，脚本默认跳过；需要强制重新生成时增加：

```bash
--force
```

生成完成后，Kling 与 ComfyUI 使用相同的后续流程：

```bash
python3 -u pipelines/preflight_videos.py \
  --run-dir "$RUN_DIR" \
  --stage generation

python3 -u pipelines/build_generation_manifest.py \
  --run-dir "$RUN_DIR" \
  --benchmark vbench2 \
  --hash

python3 -u pipelines/prepare_videos.py \
  --cases "$RUN_DIR/cases/cases.json" \
  --generated-root "$RUN_DIR/generation" \
  --video-root "$RUN_DIR/videos/prepared"

## VBench-2.0

在 run 目录中准备：

```text
runs/<run_id>/
├── config/run.yaml
├── cases/selected_full_info.json
└── videos/prepared/<dimension>/*.mp4
```

执行：

```bash
cd /Users/zhouruomiao/Documents/VBench
python pipelines/run_evaluation.py \
  --run-dir runs/20260722_ltx23_t2v_7x5
```

聚合维度分数：

```bash
python pipelines/aggregate_scores.py \
  --run-dir runs/20260722_ltx23_t2v_7x5
```

T2V 也可以复用 I2V/VBench 中不需要输入图片的 7 个视频-only 指标：

```yaml
video_only_dimensions:
  - subject_consistency
  - background_consistency
  - aesthetic_quality
  - imaging_quality
  - temporal_flickering
  - motion_smoothness
  - dynamic_degree
video_only_videos_path: videos/prepared
```

它们从 `video_only_videos_path` 读取同一批视频，不读取输入图片。`build_t2v_cases.py` 新创建的 run 配置会自动写入这 7 个维度；旧 run 可手动补充上述配置后使用统一入口运行。

### 统一 T2V/I2V 一键评测

服务器容器中可以使用统一脚本，根据 `config/run.yaml` 的 `benchmark` 自动选择 T2V 或 I2V 流程，完成离线环境设置、manifest 生成、权重检查和批量评测：

```bash
bash scripts/run_evaluation.sh /workspace/runs/<run_id>
```

若要从 `evaluation/dispatch_results.partial.json` 继续未完成的维度：

```bash
bash scripts/run_evaluation.sh /workspace/runs/<run_id> --resume
```

`benchmark: vbench2` 时，统一入口执行配置中的全部 VBench-2.0 维度，并默认追加 7 个不需要输入图片的 VBench-i2v 视频指标。`benchmark: vbench_i2v` 时，统一入口只接受需要输入图片的 `i2v_subject` 和 `i2v_background`，并要求配置 `custom_image_folder`；`camera_motion` 仍需专用标签，不会被自动加入。

旧的 `scripts/run_t2v_evaluation.sh` 仍然保留，但现在只是兼容别名，也会根据配置自动处理 I2V。

脚本会自动设置 `HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1`、`HF_DATASETS_OFFLINE=1`，并使用以下本地缓存：

```text
HF_HOME=/root/.cache/huggingface
VBENCH2_CACHE_DIR=/root/.cache/vbench2
VBENCH_CACHE_DIR=/root/.cache/vbench
TORCH_HOME=/root/.cache/vbench2/torch
VBENCH2_TORCH_HOME=/root/.cache/vbench2/torch
VBENCH_TORCH_HOME=/root/.cache/vbench/torch
```

统一环境脚本为 [scripts/vbench_env.sh](../scripts/vbench_env.sh)。它会覆盖当前 Shell 中残留的旧路径；如确实需要更换根目录，可设置 `VBENCH_CACHE_ROOT`，如：

```bash
VBENCH_CACHE_ROOT=/data/models bash scripts/run_t2v_evaluation.sh /workspace/runs/<run_id>
```

权重目录约定如下：

```text
/root/.cache/huggingface/                 # LLaVA 依赖的 SigLIP 等 HF 模型
/root/.cache/vbench2/lmms-lab/            # T2V LLaVA-Video
/root/.cache/vbench2/Qwen/                # T2V Qwen
/root/.cache/vbench2/arcface/             # T2V ArcFace
/root/.cache/vbench2/torch/               # T2V RetinaFace、CoTracker 等 Torch 权重
/root/.cache/vbench/                      # I2V 专用模型
/root/.cache/vbench/torch/                # I2V Torch 权重
```

因此运行前必须完成模型下载；缺失权重时脚本会在正式评测前停止，不会临时访问 Hugging Face。

## VBench-i2v

配置示例：

```yaml
benchmark: vbench_i2v
videos_path: videos/prepared
full_info: benchmarks/vbench_i2v/metadata/vbench2_i2v_full_info.json
resolution: 16-9
dimensions:
  - i2v_subject
  - i2v_background
custom_image_folder: cases/images
```

统一入口会调用 `run_i2v_evaluation.py`，再由适配器调用 `vbench2_beta_i2v.VBenchI2V.evaluate()`。不需要输入图片的 7 个指标不应配置在 I2V run 中，应配置到 T2V 的 `video_only_dimensions`。

I2V 批量生成中断后，可使用同一个输出目录恢复：

```bash
python pipelines/generate_i2v_batch.py \
  --cases <cases.json> \
  --template <workflow.json> \
  --output-dir <原来的输出目录> \
  --resume \
  --retries 2
```

`--resume` 会跳过 `case-XXXX` 目录中已有非空 `.mp4` 的 case；其余 case 会重新提交。批量结果会在每个 case 完成后写入 `batch_results.json`，视频下载过程中断时会保留为 `.part` 文件，不会被当作完整视频跳过。

默认使用 `prompt_text` 作为 I2V prompt。若要使用英文 prompt 字段，例如 `prompt_eval_en`，增加 `--prompt-field prompt_eval_en`。
