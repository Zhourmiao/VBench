# VBench-2.0 T2V 自动评测

这组脚本将 VBench-2.0 的 prompt-only 视频生成接入 ComfyUI。它不上传图片，要求传入一个能够独立生成视频的 T2V workflow 模板。

## 1. 构建精选 prompt cases

默认读取仓库中的 `benchmarks/vbench2_t2v/prompts/selected_7x5`，生成 11 个维度、每个 prompt 3 个样本：

```bash
cd /Users/zhouruomiao/Documents/VBench
python pipelines/core/build_t2v_cases.py \
  --output-dir runs/20260722_ltx23_t2v_7x5/cases
```

输出：

```text
runs/20260722_ltx23_t2v_7x5/cases/cases.json
runs/20260722_ltx23_t2v_7x5/cases/selected_full_info.json
```

`cases.json` 同时保存生成用 prompt、英文评测 prompt、seed、分辨率、FPS、时长和帧数。默认使用中文 prompt 生成，但使用英文 prompt 进行 VBench-2.0 标准匹配。

## 2. 运行单个 T2V case

```bash
cd /Users/zhouruomiao/Documents/VBench
python pipelines/tools/generate_t2v_single.py \
  --prompt "一个男人正在跑步" \
  --seed 2100001 \
  --template /path/to/your_t2v_workflow.json \
  --output-dir outputs/t2v_test
```

单任务也支持 `--case`，但它必须指向单个 case JSON，而不是整个 cases 数组。

默认节点 ID 兼容当前 LTX-2.3 workflow 的参数节点：

```text
正向 prompt: 267:266
负向 prompt: 267:247
seed:        267:216 267:237
宽度:        267:257
高度:        267:258
FPS:         267:260
时长:        267:225
```

如果 T2V workflow 的节点 ID 不同，使用 `--prompt-node`、`--seed-nodes`、`--width-node` 等参数覆盖。不要把 I2V workflow 当作 T2V workflow 使用；T2V 模板必须能够在没有图片输入的情况下完成采样。

## 3. 批量生成

```bash
python pipelines/core/generate_t2v_batch.py \
  --cases runs/20260722_ltx23_t2v_7x5/cases/cases.json \
  --template workflows/comfyui/t2v/video_ltx2_3_t2v.json \
  --nodes \
    http://110.126.0.52:8181 \
    http://110.126.0.52:8182 \
    http://110.126.0.52:8183 \
    http://110.126.0.52:8184 \
  --concurrency 1 \
  --output-dir runs/20260722_ltx23_t2v_7x5/generation
```

批量覆盖视频时长（不修改原始 `cases.json`）：

```bash
python pipelines/core/generate_t2v_batch.py \
  --cases runs/20260722_ltx23_t2v_7x5/cases/cases.json \
  --template workflows/comfyui/t2v/video_ltx2_3_t2v.json \
  --nodes http://110.126.0.52:8183 http://110.126.0.52:8184 \
  --concurrency 2 \
  --duration 10 \
  --output-dir runs/20260722_ltx23_t2v_7x5/generation_10s
```

每个 case 的输出目录包含 `case.json`、实际提交的 `workflow.json`、`research_results.jsonl` 和 `{case_id}.mp4`。`research_results.jsonl` 会记录 `started_at`、`finished_at`、`elapsed_sec`、最终生效参数和状态来源。

批量目录另外生成 `batch_results.json` 和 `batch_timing.json`。任务轮询优先使用 `/api/jobs/<prompt_id>`；如果该接口超时或返回 HTTP 错误，会自动回退到标准 ComfyUI `/history/<prompt_id>`。

如果批量过程中客户端网络中断，可以使用相同的 `--output-dir` 加上 `--resume` 重新运行：已有非空 `{case_id}.mp4` 的 case 会自动跳过，其他 case 会重新提交。可通过 `--retries N` 设置失败后的额外重试次数，例如：

```bash
python pipelines/core/generate_t2v_batch.py \
  --cases runs/20260722_ltx23_t2v_7x5/cases/cases.json \
  --template workflows/comfyui/t2v/video_ltx2_3_t2v.json \
  --output-dir runs/20260722_ltx23_t2v_7x5/generation \
  --resume \
  --retries 2
```

`--resume` 按最终视频文件判断完成状态；无法恢复客户端断线时 ComfyUI 内部已经提交但尚未下载的单个任务，因此这类任务可能会被重新提交。

如果需要在已有 run 中增加 prompt 或评测维度，先追加 cases 并保持旧 case ID：

```bash
python pipelines/core/build_t2v_cases.py \
  --output-dir runs/<run_id>/cases \
  --append
```

然后再使用上面的 `generate_t2v_batch.py --resume`。追加模式按维度、英文 prompt 和 sample index 匹配已有 case，旧视频不会因新增 prompt 而重新编号。

默认使用 case JSON 中的 `prompt_input`。如果要使用英文 prompt 字段（例如 `prompt_eval_en`），增加 `--prompt-field prompt_eval_en`：

```bash
python pipelines/core/generate_t2v_batch.py \
  --cases runs/20260722_ltx23_t2v_7x5/cases/cases.json \
  --template workflows/comfyui/t2v/video_ltx2_3_t2v.json \
  --output-dir runs/20260722_ltx23_t2v_7x5/generation \
  --prompt-field prompt_eval_en \
  --resume \
  --retries 2
```

## 4. 整理为 VBench-2.0 视频目录

```bash
python pipelines/core/prepare_videos.py \
  --cases runs/20260722_ltx23_t2v_7x5/cases/cases.json \
  --generated-root runs/20260722_ltx23_t2v_7x5/generation \
  --video-root runs/20260722_ltx23_t2v_7x5/videos/prepared
```

脚本会按以下规则命名：

```text
{英文评测 prompt[:180]}-{sample_index}.mp4
```

并按维度放入子目录。只要有一个视频缺失，脚本就会返回失败并生成 `prepare_report.json`。

## 5. 运行 VBench-2.0

VBench-2.0 的标准模式按维度读取视频目录，因此精选集应逐维度运行：

```bash
cd /Users/zhouruomiao/Documents/VBench
python pipelines/core/run_evaluation.py \
  --run-dir runs/20260722_ltx23_t2v_7x5
```

统一入口会逐个维度调用 VBench-2.0，并将日志与结果保存到 `runs/20260722_ltx23_t2v_7x5/evaluation/`。`selected_full_info.json` 保留了官方 `auxiliary_info`，因此适用于 `Mechanics`、`Motion_Rationality`、`Complex_Plot` 等不能直接走 custom input 的维度。
