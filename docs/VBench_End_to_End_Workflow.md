# VBench 端到端评测流程

本文梳理 T2V、I2V、ComfyUI、闭源 API、直接上传、数据准备、单指标评测和批量评测的完整流程。

## 1. 总体流程

    生成配置/工作流
      ↓
    生成原始视频
      ↓
    保存生成元数据
      ↓
    统一整理为 VBench 输入格式
      ↓
    运行单个指标或批量指标
      ↓
    保存逐视频结果、总分和日志

建议每次实验使用独立的 run_id：

    runs/<run_id>/
    ├── config/
    │   ├── run.yaml
    │   └── workflow_snapshot.json
    ├── cases/
    │   ├── cases.json
    │   ├── selected_full_info.json
    │   └── images/
    ├── generation/
    ├── videos/prepared/
    └── evaluation/

生成结果与评测结果分离，模型通过缓存目录挂载。

## 2. ComfyUI 生成 T2V

### 2.1 测试案例

每个案例至少包含：

    {
      "case_id": "t2v-0001",
      "prompt_eval_en": "A person is pouring olive oil into a frying pan.",
      "sample_index": 0,
      "dimension": ["Mechanics"],
      "seed": 10001
    }

同时保存 workflow JSON、模型 checkpoint、LoRA、seed、分辨率、FPS、时长、采样器和生成状态。

### 2.2 原始视频目录

当前整理脚本约定：

    runs/<run_id>/generation/<case_id>/
    ├── <case_id>.mp4
    └── case.json

例如：

    runs/20260722_ltx23_t2v_7x5/generation/t2v-0001/t2v-0001.mp4

如果 ComfyUI 输出 UUID，应在整理阶段通过 case_id 映射，不建议直接使用 UUID 作为评测文件名。

### 2.3 T2V 整理命令

    python /workspace/pipelines/prepare_videos.py \
      --cases /workspace/runs/<run_id>/cases/cases.json \
      --generated-root /workspace/runs/<run_id>/generation \
      --video-root /workspace/runs/<run_id>/videos/prepared

整理后：

    videos/prepared/
    ├── Mechanics/
    │   ├── A person is pouring olive oil into a frying pan.-0.mp4
    │   └── ...
    ├── Motion_Rationality/
    └── Complex_Plot/

当前 T2V 文件名格式为：

    <prompt_eval_en>-<sample_index>.mp4

VBench 会从文件名恢复 prompt，因此 prompt 文本、标点和 sample 后缀必须保持一致。

## 3. ComfyUI 生成 I2V

### 3.1 原始 I2V 目录

    <batch_root>/
    ├── batch_results.json
    ├── case-0001/
    │   ├── <uuid>.mp4
    │   └── research_results.jsonl
    ├── case-0002/
    │   └── <uuid>.mp4
    └── ...

batch_results.json 中可能使用 i2v-0001，而目录使用 case-0001，整理脚本会进行映射。

### 3.2 I2V 整理命令

    python /workspace/pipelines/prepare_i2v_videos.py \
      --batch-root /workspace/runs/<batch>/opt3_batch \
      --output-root /workspace/runs/<run_id>/videos/prepared \
      --image-root /workspace/benchmarks/vbench_i2v/images/16-9 \
      --image-output /workspace/runs/<run_id>/cases/images

当前 I2V 使用公共视频目录：

    videos/prepared/
    ├── A little girl, lost in thought, is quietly sitting on the bus-0.mp4
    └── ...

    cases/images/
    ├── A little girl, lost in thought, is quietly sitting on the bus.jpg
    └── ...

视频 prompt 和输入图片必须一一对应。一个图片可以复用，但必须创建与视频 prompt 完全一致的图片别名。

## 4. Kling 等闭源 API

### 4.1 统一生成清单

无论视频来自 ComfyUI、Kling 还是手工上传，都可以在生成完成后建立统一清单：

    python /workspace/pipelines/build_generation_manifest.py \
      --run-dir /workspace/runs/<run_id> \
      --benchmark vbench2 \
      --hash

I2V 使用：

    python /workspace/pipelines/build_generation_manifest.py \
      --run-dir /workspace/runs/<run_id> \
      --benchmark vbench_i2v \
      --source-root /workspace/runs/<run_id>/generation \
      --hash

脚本生成 `generation/manifest.jsonl` 和 `generation/manifest_summary.json`。每条记录包含 `case_id`、prompt、维度、生成模式、视频相对路径、文件大小、状态、案例原始字段和可选 SHA-256。缺失视频时返回非 0，避免后续误把不完整数据当作完整实验。

仓库现在提供 `pipelines/kling_generate_t2v.py`，在保留原 Kling API 调用、轮询和下载逻辑的基础上，输出 VBench 统一格式：

    runs/<run_id>/generation/
    ├── manifest.jsonl
    ├── t2v-0001/
    │   ├── t2v-0001.mp4
    │   └── generation.json
    └── t2v-0002/
        ├── t2v-0002.mp4
        └── generation.json

generation.json 至少保存：

    {
      "case_id": "t2v-0001",
      "provider": "kling",
      "mode": "t2v",
      "prompt": "A person is pouring olive oil into a frying pan.",
      "request_id": "...",
      "local_video": "generation/t2v-0001/t2v-0001.mp4",
      "status": "success",
      "created_at": "2026-07-29T00:00:00Z"
    }

I2V 还要记录输入图片路径或 hash、image URL/上传 ID、aspect ratio 和 duration。

运行脚本后会写入：

    generation/<case_id>/<case_id>.mp4
    generation/<case_id>/case.json
    generation/<case_id>/generation.json
    generation/manifest.jsonl

当前脚本支持批量 cases、单 prompt、已有 task_id、失败记录和已完成视频跳过。API 结果仍建议在正式评测前执行视频格式与元数据检查。

## 5. 直接上传测试视频

支持直接上传，但上传后必须整理为标准结构。

### T2V 上传

    /workspace/runs/<run_id>/generation/<case_id>/<case_id>.mp4

同时准备：

    /workspace/runs/<run_id>/cases/cases.json

再执行 prepare_videos.py，不要把视频直接散落在 videos/prepared。

### I2V 上传

    /workspace/runs/<run_id>/generation/<batch_root>/case-0001/<uuid>.mp4
    /workspace/runs/<run_id>/cases/images/<prompt>.jpg

再执行 prepare_i2v_videos.py。

### 上传视频格式规范

正式评测前应检查：

- .mp4 后缀；
- 文件非空且可被 OpenCV、Decord 读取；
- 帧数大于 1；
- FPS、时长、分辨率符合配置；
- 没有全黑、损坏或异常封装；
- 文件名没有被系统自动改名或截断。

## 6. 按指标准备数据

## 6.2 模型与权重预检查

正式评测前只检查指定维度的本地依赖，不自动下载：

    python /workspace/pipelines/check_models.py \
      --run-dir /workspace/runs/<run_id>

也可以只检查单个指标：

    python /workspace/pipelines/check_models.py \
      --run-dir /workspace/runs/<run_id> \
      --dimensions Complex_Plot

脚本根据 T2V/I2V 和指标选择模型配置，检查模型目录、权重文件、HF 缓存以及关键 Python 包，输出 `evaluation/model_preflight_report.json`。脚本不会触发下载；报告通过后再启动评测，缺失项则按报告中的路径准备权重。

## 6.3 实时日志与断点续跑

批量评测默认实时显示子进程输出，并同步写入：

    /workspace/runs/<run_id>/evaluation/evaluation.log

每完成一个指标，会额外保存：

    evaluation/dispatch_results.partial.json

如果中途断开，可以继续运行：

    python /workspace/pipelines/run_evaluation.py \
      --run-dir /workspace/runs/<run_id> \
      --resume

已成功完成的指标会跳过，失败或未开始的指标会继续执行。最终仍会生成 `evaluation/dispatch_results.json`。I2V 保持遇到第一个失败指标即停止的策略。

## 6.1 视频预检查（建议作为 prepare 后的固定门禁）

T2V 原始视频整理前检查：

    python /workspace/pipelines/preflight_videos.py \
      --run-dir /workspace/runs/<run_id> \
      --stage generation

I2V 视频整理后检查：

    python /workspace/pipelines/preflight_videos.py \
      --run-dir /workspace/runs/<run_id> \
      --stage prepared

脚本会写入 `videos/preflight_<stage>_report.json`，检查文件存在、非空、视频容器可读、首帧可读、帧数、FPS、分辨率、时长，以及 I2V 的输入图片映射。返回码为 0 才继续 prepare 或 evaluate；失败时先查看报告，不要直接启动模型评测。

### T2V

T2V 必须按指标拆目录：

    videos/prepared/<dimension>/<prompt>-<sample_index>.mp4

T2V wrapper 会将该目录直接传给 VBench。

### I2V

I2V 使用公共目录：

    videos/prepared/<prompt>-<index>.mp4
    cases/images/<prompt>.jpg

### 特殊数据要求

不能只修改 --dimension 来制造特殊指标数据：

- camera_motion 必须有 camera pans left、camera zooms in 等镜头描述；
- i2v_subject、subject_consistency 必须有输入图片；
- i2v_background 必须有输入图片和 DreamSim；
- Motion_Rationality、Mechanics、Complex_Plot 等必须有对应 prompt 和辅助问题。

## 7. 只运行一个指标

### T2V

    python /workspace/source/VBench-2.0/evaluate.py \
      --videos_path /workspace/runs/<run_id>/videos/prepared/Mechanics \
      --full_json_dir /workspace/runs/<run_id>/cases/selected_full_info.json \
      --output_path /workspace/runs/<run_id>/evaluation/Mechanics \
      --dimension Mechanics \
      --mode vbench_standard \
      --load_ckpt_from_local True \
      --read_frame False

### I2V

    python /workspace/pipelines/run_i2v_evaluation.py \
      --videos-path /workspace/runs/<run_id>/videos/prepared \
      --full-info /workspace/benchmarks/vbench_i2v/metadata/vbench2_i2v_full_info.json \
      --output-path /workspace/runs/<run_id>/evaluation/subject_consistency \
      --dimension subject_consistency \
      --resolution 16-9 \
      --custom-image-folder /workspace/runs/<run_id>/cases/images \
      --local

建议保存实时日志：

    ... 2>&1 | tee /workspace/runs/<run_id>/evaluation/<dimension>/live.log

## 8. 运行所有已适配指标

### T2V 配置

    benchmark: vbench2
    dimensions:
      - Complex_Plot
      - Human_Identity
      - Mechanics
      - Motion_Order_Understanding
      - Motion_Rationality
      - Multi-View_Consistency
    stop_on_error: false

运行：

    python /workspace/pipelines/run_evaluation.py \
      --run-dir /workspace/runs/<run_id>

T2V 按顺序运行；stop_on_error 为 false 时某个指标失败仍会继续。

### I2V 配置

    benchmark: vbench_i2v
    dimensions:
      - i2v_subject
      - i2v_background
      - subject_consistency
      - background_consistency
      - aesthetic_quality
      - imaging_quality
      - temporal_flickering
      - motion_smoothness
      - dynamic_degree

运行命令相同：

    python /workspace/pipelines/run_evaluation.py \
      --run-dir /workspace/runs/<run_id>

I2V 当前遇到错误会停止，批量运行前应确认所有权重和依赖。

## 9. 缺口与优化建议

### 必须补齐

1. 增加 Kling 等 API 结果导入器；
2. 增加上传预检查；
3. 增加统一模型/权重检查脚本，覆盖 LLaVA 的 SigLIP 视觉塔；
4. 将 NumPy、OpenCV、timm、pyiqa 等版本固定到 Docker 构建流程；
5. 将生成参数、模型版本、工作流和输入图片 hash 保存到 manifest。

### 建议优化

1. run_evaluation.py 改为实时输出日志；当前 capture_output=True 会隐藏子进程运行过程；
2. 增加断点续跑，成功的维度自动跳过；
3. T2V 和 I2V 都支持 stop_on_error；
4. 每个指标结束后执行 gc.collect() 和 torch.cuda.empty_cache()；
5. 准备阶段输出 FPS、时长、分辨率、帧数、文件 hash 和缺失原因；
6. 内部使用稳定 case_id，不要长期依赖超长 prompt 作为文件名；
7. 每个指标先运行 1 个视频的 smoke test，再运行完整数据集。

## 10. 推荐最终标准流程

    1. 创建 run_id
    2. 保存 cases.json、输入图片和生成配置
    3. 通过 ComfyUI、闭源 API 或上传得到原始视频
    4. 保存 generation manifest 和模型/参数信息
    5. 执行视频格式与元数据预检查
    6. 使用对应 prepare 脚本整理
    7. 检查 prepare_report.json
    8. 检查模型和权重
    9. 先运行单个指标 smoke test
    10. 再运行单指标完整评测
    11. 最后批量运行全部已适配指标
    12. 保存 evaluation、日志、dispatch_results.json 和环境版本
