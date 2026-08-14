# VBench Pipeline 使用说明

`pipelines` 分为两个目录：

- `pipelines/core/`：正式评测流程需要的核心脚本。
- `pipelines/tools/`：单样例调试、结果恢复、实验归档和结果比较工具。

本文重点介绍 `pipelines/core/` 和完整的 T2V 评测流程。

## 一、`pipelines/core/` 中的脚本

### 1. 测试集构建

| 脚本 | 功能 |
| --- | --- |
| `build_t2v_cases.py` | 根据 VBench-2.0 的 prompt、manifest 和 metadata 构建 T2V `cases.json`，同时生成 `selected_full_info.json` 和 `run.yaml`。支持指定维度、样本数以及使用 `--append` 向已有 run 追加样例。 |
| `select_i2v_metadata.py` | 从完整 I2V metadata 中筛选同时满足指定维度的样例。 |
| `build_i2v_cases.py` | 根据 I2V prompt、metadata 和输入图片生成 I2V cases，记录输入图片、prompt、seed、分辨率和时长等信息。 |

### 2. 视频生成

下面的脚本是不同生成后端的入口，单次实验通常选择其中一个：

| 脚本 | 功能 |
| --- | --- |
| `generate_t2v_batch.py` | 通过 ComfyUI 批量生成 T2V 视频，支持多个节点、并发、重试和 `--resume`。 |
| `generate_i2v_batch.py` | 通过 ComfyUI 批量生成 I2V 视频，支持多个节点、并发、重试和断点恢复。 |
| `kling_generate_t2v.py` | 调用 Kling API 批量生成 T2V 视频，并保存为 VBench 的 generation 目录格式。 |
| `generate_minimax_h3_api_batch.py` | 调用本地 MiniMax H3 HTTP API 批量生成 T2V/T2VA 视频。 |
| `generate_minimax_h3_t2v.py` | MiniMax H3 的 ComfyUI 适配入口，自动识别 H3 工作流节点后复用 T2V 批量生成逻辑。 |

`t2v_common.py` 是 T2V 生成脚本共用的函数库，负责 ComfyUI 任务提交、状态轮询、结果下载和 JSON 记录，不需要单独运行。

### 3. 视频检查和整理

| 脚本 | 功能 |
| --- | --- |
| `preflight_videos.py` | 检查视频是否存在、能否读取，以及分辨率、FPS、时长、帧数等是否符合预期。 |
| `prepare_videos.py` | 将 T2V generation 目录中的视频按 VBench 维度整理到 `videos/prepared/`。 |
| `prepare_i2v_videos.py` | 将 I2V generation 输出和输入图片整理为 VBench-i2v 所需的目录结构。 |

### 4. 评测环境和评测执行

| 脚本 | 功能 |
| --- | --- |
| `check_models.py` | 检查本地 VBench 模型权重、缓存和 Python 依赖是否齐全，不负责下载模型。 |
| `run_evaluation.py` | 统一评测入口，根据 `run.yaml` 的 `benchmark` 和维度配置启动 T2V 或 I2V 评测。 |
| `run_video_only_evaluation.py` | 执行不需要输入图片的视频指标，例如主体一致性、背景一致性、审美质量和运动平滑度。通常由 `run_evaluation.py` 调用。 |
| `run_i2v_evaluation.py` | I2V 评测适配器，调用 VBench-i2v 的评测 API。通常由 `run_evaluation.py` 调用。 |
| `aggregate_scores.py` | 读取各维度评测结果，生成 run 级别的分数汇总。 |

## 二、完整 T2V 评测流程

T2V 的完整流程如下：

```text
创建 run 目录
    ↓
生成 cases.json
    ↓
检查 ComfyUI 节点
    ↓
批量生成视频
    ↓
生成 manifest、整理视频目录、检查评测模型
    ↓
执行 VBench 评测
    ↓
聚合分数
```
其中“生成 manifest、整理视频目录、检查评测模型和执行评测”已经统一收口到 `scripts/run_evaluation.sh`，生成视频完成后直接执行该脚本即可。

### 1. 创建 run 目录

```bash
cd /Users/zhouruomiao/Documents/VBench

export RUN_ID=20260814_ltx23_t2v
export RUN_DIR=/Users/zhouruomiao/Documents/VBench/runs/$RUN_ID

mkdir -p "$RUN_DIR"/{config,cases,generation,videos/prepared,evaluation}
```

每个实验使用独立的 `run` 目录，避免不同模型或不同 workflow 的生成结果互相覆盖。

### 2. 生成 `cases.json`

```bash
python3 pipelines/core/build_t2v_cases.py \
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

`build_t2v_cases.py` 默认从 `benchmarks/vbench2_t2v/` 读取 manifest、prompt 和 metadata。它会在 run 目录缺少配置时自动创建 `config/run.yaml`；如果配置已经存在，则不会覆盖已有配置。

已有 run 追加 prompt 时使用 `--append`：

```bash
python3 pipelines/core/build_t2v_cases.py \
  --output-dir "$RUN_DIR/cases" \
  --append
```

追加模式按照“维度 + 英文 prompt + sample_index”匹配旧 case，保持旧 `case_id` 不变，只为新增 prompt 创建新 case。已有配置中的维度列表也会同步更新。之后使用生成脚本的 `--resume`，旧视频会跳过，只生成新增 case。

### 3. 检查 ComfyUI 节点
需要使用 univpn 连接110.126.0.52服务器

```bash
curl --max-time 10 http://110.126.0.52:8181/system_stats
curl --max-time 10 http://110.126.0.52:8182/system_stats
```

两个节点都返回 JSON 后再提交批量任务。如果使用其他 ComfyUI 地址，在生成命令中替换 `--nodes` 参数。

### 4. 调用 ComfyUI 批量生成

推荐使用 generation 配置文件，集中管理 workflow 路径、ComfyUI 节点、prompt/seed/尺寸/FPS/时长字段映射和默认生成参数：

```bash
python3 -u pipelines/core/generate_t2v_batch.py \
  --cases "$RUN_DIR/cases/cases.json" \
  --generation-config configs/generation/wan22_t2v.yaml \
  --output-dir "$RUN_DIR/generation" \
  --resume \
  --retries 1 \
  --retry-delay 10
```

切换到 LTX-2.3 时替换配置文件：

```bash
--generation-config configs/generation/ltx23_t2v.yaml
```

命令行参数可以覆盖配置文件中的同名参数。

也可以直接传入 ComfyUI API 格式的 workflow：

```bash
python3 -u pipelines/core/generate_t2v_batch.py \
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

`--prompt-field prompt_eval_en` 表示使用英文评测 prompt，而不是 `prompt_input` 中的中文生成 prompt。`--resume` 会跳过已经存在的非空视频。

Wan 工作流的关键节点示例：

```text
正向 prompt：89.text
负向 prompt：72.text
seed：81.noise_seed、78.noise_seed
宽度：74.width
高度：74.height
FPS：88.fps
视频帧数：74.length
```

如果配置中使用：

```yaml
duration: 10
fps: 25
duration_scale: 25
duration_offset: 1
```

则 10 秒视频会写入：

```text
length = 10 × 25 + 1 = 251 帧
```

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

### 5. 使用统一脚本整理视频并执行评测

在蓝区 140.210.239.19 3015端口环境上 使用docker（zhou-videobench-dev:v1）镜像

视频生成完成后，从项目根目录直接运行：

```bash
bash scripts/run_evaluation.sh "$RUN_DIR"
```

该脚本会自动完成：

1. 根据 `cases.json` 和 generation 目录生成 `generation/manifest.jsonl`；
2. 调用 `pipelines/core/prepare_videos.py`，将视频整理到 VBench 要求的目录；
3. 调用 `pipelines/core/check_models.py`，检查模型权重和依赖；
4. 调用 `pipelines/core/run_evaluation.py`，执行所有配置的 VBench 维度。

因此正常情况下不需要手动分别执行 `build_generation_manifest.py`、`prepare_videos.py`、`check_models.py` 和 `run_evaluation.py`。

如果评测中断，需要从已有的部分结果继续：

```bash
bash scripts/run_evaluation.sh "$RUN_DIR" --resume
```

评测日志和结果保存在：

```text
$RUN_DIR/evaluation/
```

### 6. 聚合分数

评测完成后运行：

```bash
python3 pipelines/core/aggregate_scores.py \
  --run-dir "$RUN_DIR"
```

该脚本读取 `$RUN_DIR/evaluation/` 中各个维度的结果，并生成 run 级别的分数汇总。

## 三、其他生成后端

### Kling API

Kling 使用同样的 `cases.json`，但不经过 ComfyUI：

```bash
export KLING_API_KEY="你的_Kling_API_Key"

python3 -u pipelines/core/kling_generate_t2v.py \
  --cases "$RUN_DIR/cases/cases.json" \
  --output-root "$RUN_DIR/generation" \
  --model kling-3.0-turbo \
  --duration 5 \
  --aspect-ratio 16:9 \
  --poll-interval 10 \
  --timeout 900
```

Kling 生成完成后，同样执行：

```bash
bash scripts/run_evaluation.sh "$RUN_DIR"
python3 pipelines/core/aggregate_scores.py --run-dir "$RUN_DIR"
```

### MiniMax H3

MiniMax H3 有两个生成入口：

```text
pipelines/core/generate_minimax_h3_api_batch.py  # 本地 HTTP API
pipelines/core/generate_minimax_h3_t2v.py        # ComfyUI workflow
```

生成完成后也复用同一套 `run_evaluation.sh` 和 `aggregate_scores.py`。

## 四、辅助工具

辅助工具不属于每次评测都必须执行的主流程：

| 脚本 | 功能 |
| --- | --- |
| `tools/generate_t2v_single.py` | 生成单个 T2V case，用于调试 workflow 和节点映射。 |
| `tools/generate_i2v_single.py` | 生成单个 I2V case，用于调试。 |
| `tools/download_outputs.py` | 从已有远程结果记录中重新下载视频，用于下载中断后的恢复。 |
| `tools/build_generation_manifest.py` | 生成视频文件清单；正式评测时由 `scripts/run_evaluation.sh` 自动调用。 |
| `tools/compare_case_scores.py` | 比较两个模型在相同 case 上的逐样例分数，并生成 JSON、CSV 和 HTML 报告。 |

例如比较两个已经完成评测的 run：

```bash
python3 pipelines/tools/compare_case_scores.py \
  --model-a-run runs/20260729_ltx23_t2v \
  --model-b-run runs/20260807_kling_t2v \
  --model-a-name LTX2.3 \
  --model-b-name Kling \
  --output-dir runs/compare_ltx23_vs_kling
```
