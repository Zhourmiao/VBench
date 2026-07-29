# LTX-2.3 I2V 外部调研测试

这组脚本用于在独立的 ComfyUI 节点上运行 LTX-2.3 I2V 实验，不修改 MoG Gateway，也不改写仓库内的稳定 workflow。

正式入口位于项目根目录的 `pipelines/`：

- 单任务：`pipelines/generate_i2v_single.py`
- 批处理：`pipelines/generate_i2v_batch.py`
- case 生成：`pipelines/build_i2v_cases.py`
- 默认模板：`workflows/comfyui/i2v/Opt3_balanced_i2v075_lora060.json`

## 前置条件

请从项目根目录执行命令：

```bash
cd /Users/zhouruomiao/Documents/VBench
```

需要 Python 3.10 或更高版本，以及 `requests`：

```bash
python -m pip install requests
```

远端 ComfyUI 节点必须已加载 LTX-2.3 所需 checkpoint、LoRA、VAE 和自定义节点，并提供以下接口：

- `POST /upload/image`
- `POST /api/prompt`
- `GET /api/jobs/<prompt_id>`
- `GET /history/<prompt_id>`（`/api/jobs` 不可用时的标准 ComfyUI 回退接口）
- `GET /view`

默认节点为 `110.126.0.52:8181` 至 `8184`。如果节点地址不同，请通过 `--nodes` 显式传入。运行前应先确认节点可访问；脚本不会自动重试失败任务。

## 单任务运行

使用模板默认参数：

```bash
python pipelines/generate_i2v_single.py \
  --template workflows/comfyui/i2v/Opt3_balanced_i2v075_lora060.json \
  --image /path/to/input.jpg \
  --prompt "a dog running on the beach, smooth camera movement" \
  --output-dir runs/ltx23_i2v_manual/exp_default
```

只修改 CFG 和随机种子：

```bash
python pipelines/generate_i2v_single.py \
  --template workflows/comfyui/i2v/Opt3_balanced_i2v075_lora060.json \
  --image /path/to/input.jpg \
  --prompt "a dog running on the beach, smooth camera movement" \
  --cfg 1.2 \
  --seed 12345 \
  --nodes http://110.126.0.52:8183 \
  --output-dir runs/ltx23_i2v_manual/exp_cfg_1_2_seed_12345
```

可覆盖的参数包括：`--sampler`、`--cfg`、`--lora-strength`、`--image-strength-1`、`--image-strength-2`、`--seed`、`--width`、`--height`、`--duration` 和 `--fps`。未传入的参数保留模板值；`research_results.jsonl` 会记录最终生效的完整参数，而不只是命令行覆盖项。

单任务会把视频保存为 `<output-dir>/<prompt_id>.mp4`，并在同一目录追加一条 `research_results.jsonl` 记录。任务成功时退出码为 0；上传、提交、轮询、下载或服务端任务失败时退出码非 0，但仍会保留错误记录。脚本优先轮询 `/api/jobs/<prompt_id>`；该接口超时或返回 HTTP 错误时，会自动切换到标准 ComfyUI `/history/<prompt_id>`，因此节点页面已经显示完成的视频时仍有机会正常识别并下载。

脚本使用 `--nodes` 的第一个节点。测试其他节点时只传入一个地址即可：

```bash
--nodes http://110.126.0.52:8183
```

## 批量运行

### 生成 cases.json

从当前 VBench-i2v 精选 prompt、metadata 和 16:9 输入图像生成案例文件：

```bash
python pipelines/build_i2v_cases.py \
  --prompts benchmarks/vbench_i2v/prompts/all_unique_prompts.txt \
  --full-info benchmarks/vbench_i2v/metadata/vbench2_i2v_full_info.json \
  --image-root benchmarks/vbench_i2v/images/16-9 \
  --output runs/i2v_eval/all/cases.json
```

默认视频参数为 1280×720、5 秒、25 FPS，可通过 `--width`、`--height`、`--duration` 和 `--fps` 覆盖。生成器会在写文件前检查每条 prompt 是否存在于 metadata，以及对应图片是否存在。

当前生成的文件包含 41 条 case。若更换 prompt 文件或图片目录，建议使用新的输出路径，避免覆盖已有实验输入。

仓库中现成的 I2V subject 案例为：

```text
runs/20260722_ltx23_i2v_subject/cases/cases.json
```

运行批处理：

```bash
python pipelines/generate_i2v_batch.py \
  --cases runs/20260722_ltx23_i2v_subject/cases/cases.json \
  --template workflows/comfyui/i2v/Opt3_balanced_i2v075_lora060.json \
  --nodes http://110.126.0.52:8181 http://110.126.0.52:8182 http://110.126.0.52:8183 http://110.126.0.52:8184 \
  --concurrency 1 \
  --output-dir runs/ltx23_i2v_manual/opt3_batch
```

案例中的 `image` 路径可以是绝对路径，也可以相对于 `cases.json` 解析；若路径本身不存在，脚本还会尝试 `cases.json` 同级的 `images/` 目录。案例中的 `prompt_text`、`sampler`、`cfg`、`lora_strength`、`image_strength_1`、`image_strength_2`、`seed`、`width`、`height`、`duration` 和 `fps` 会作为该样本的参数覆盖模板值。

批处理按样本序号轮询分配节点。建议先使用 `--concurrency 1` 确认单任务成功，再提高到 2 或 4；并发数不应超过可用节点和节点显存承载能力。

每条样本输出到：

```text
<output-dir>/case-XXXX/
├── <prompt_id>.mp4
└── research_results.jsonl
```

批量汇总写入：

```text
<output-dir>/batch_results.json
```

汇总中的 `status` 以单任务退出码为准。只有视频生成并下载成功的任务才会标记为 `success`。

## 后续 VBench 评测

本目录只负责生成视频，不自动计算 VBench 分数。生成结果需要先按对应 run 的目录结构整理到 `videos/prepared/`，再使用项目级评测入口：

```bash
python pipelines/run_evaluation.py \
  --run-dir runs/20260722_ltx23_i2v_subject
```

具体评测维度和 run 配置以 `runs/<run_id>/config/run.yaml` 为准。

## 常见问题

- `找不到案例图片`：检查 `cases.json` 中的路径，或将图片放入其同级 `images/` 目录。
- `模板文件不存在`：从项目根目录执行，或传入模板的绝对路径。
- 任务状态为 `completed_no_output`：ComfyUI 任务结束但没有找到可下载的视频输出，需要检查 workflow 的保存节点和远端节点日志。
- 节点连接失败或轮询超时：检查网络、节点地址、ComfyUI 服务状态及上述 API 是否可用。
