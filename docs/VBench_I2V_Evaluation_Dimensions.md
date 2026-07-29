# VBench I2V 评测指标说明

本文记录当前 VBench I2V 评测的指标、输入数据、模型权重、计算逻辑和运行方式。

## 一、整体流程

```text
ComfyUI 生成 I2V 视频
  ↓
整理视频和输入图片
  ↓
构建 I2V full_info.json
  ↓
加载本地模型和权重
  ↓
逐视频读取帧或图像特征
  ↓
计算单视频分数
  ↓
汇总指标平均分
  ↓
保存到 evaluation/<dimension>
```

I2V 与 T2V 的目录组织不同。I2V 使用一份公共视频目录和一份输入图片目录：

```text
runs/<run_id>/
├── videos/prepared/       # 整理后的视频
├── cases/images/          # 与视频 prompt 对应的输入图片
└── evaluation/<dimension> # 各指标结果
```

I2V 不要求将视频复制到 `prepared/<指标名>`。不同指标读取同一个 `videos/prepared`，由 `--dimension` 决定当前评测内容。

## 二、当前指标状态

| 指标 | 主要内容 | 当前状态 |
|---|---|---|
| `i2v_subject` | 输入图片中的主体是否保持 | 已完成 |
| `i2v_background` | 输入图片中的背景/整体视觉是否保持 | 已完成 |
| `subject_consistency` | 视频内部主体跨帧一致性 | 已完成 |
| `background_consistency` | 视频内部背景跨帧一致性 | 已完成 |
| `aesthetic_quality` | 画面美学质量 | 已完成 |
| `imaging_quality` | 清晰度、失真、技术画质 | 已完成 |
| `temporal_flickering` | 时间上的闪烁程度 | 已完成 |
| `motion_smoothness` | 运动平滑度 | 已完成 |
| `dynamic_degree` | 视频动态程度 | 已完成 |
| `camera_motion` | 镜头运动是否符合 prompt | 待专用数据 |

## 三、指标与权重

| 指标 | 使用组件 | 默认缓存位置 |
|---|---|---|
| `i2v_subject` | DINO ViT-B/16 | `/root/.cache/vbench/dino_model/` |
| `i2v_background` | DreamSim ensemble | `/root/.cache/vbench/dreamsim_ckpts/` |
| `subject_consistency` | DINO ViT-B/16 | `/root/.cache/vbench/dino_model/` |
| `background_consistency` | CLIP ViT-B/32 | `/root/.cache/vbench/clip_model/ViT-B-32.pt` |
| `aesthetic_quality` | CLIP ViT-L/14 + LAION aesthetic predictor | `/root/.cache/vbench/clip_model/`、`aesthetic_model/` |
| `imaging_quality` | MUSIQ-SPAQ | `/root/.cache/vbench/pyiqa_model/` |
| `temporal_flickering` | OpenCV，无模型权重 | 无 |
| `motion_smoothness` | AMT-S | `/root/.cache/vbench/amt_model/amt-s.pth` |
| `dynamic_degree` | RAFT | `/root/.cache/vbench/raft_model/models/raft-things.pth` |
| `camera_motion` | CoTracker2 | `/root/.cache/vbench/torch/hub/checkpoints/cotracker2.pth` |

## 四、`i2v_subject`：I2V 主体保持

比较输入图片中的主体与生成视频中的主体是否一致。

1. 使用 DINO 提取输入图片特征。
2. 对视频帧逐帧提取 DINO 特征。
3. 计算每帧与输入图片的相似度。
4. 计算相邻帧之间的相似度。
5. 按以下权重汇总：

```text
视频分数 = 0.4 × 输入图片相似度最大值
        + 0.3 × 相邻帧相似度均值
        + 0.3 × 相邻帧相似度最小值
```

指标总分为所有视频分数的平均值。

## 五、`i2v_background`：I2V 背景/整体保持

使用 DreamSim 比较输入图片与视频帧的视觉特征，关注背景和整体场景是否保持。

其计算结构与 `i2v_subject` 类似：

```text
视频分数 = 0.4 × 与输入图片相似度最大值
        + 0.3 × 相邻帧相似度均值
        + 0.3 × 相邻帧相似度最小值
```

## 六、`subject_consistency`：视频内部主体一致性

判断主体在视频连续帧中是否保持一致，不直接比较输入图片。

1. 使用 DINO 提取每帧特征。
2. 每帧同时与前一帧和第一帧比较。
3. 当前帧分数为两种相似度的平均值。
4. 对所有帧求平均，得到单视频分数。

```text
当前帧分数 = (与前一帧相似度 + 与第一帧相似度) / 2
视频分数 = 所有当前帧分数的平均值
```

## 七、`background_consistency`：视频内部背景一致性

使用 CLIP ViT-B/32 判断视频背景和整体场景的时间稳定性。

1. 提取视频帧的 CLIP 特征。
2. 每帧与前一帧、第一帧计算余弦相似度。
3. 对相似度取非负值并求平均。
4. 对所有视频分数求平均。

## 八、`aesthetic_quality`：美学质量

判断构图、色彩、视觉吸引力和整体观感。

1. 使用 CLIP ViT-L/14 提取每帧特征。
2. 使用 LAION aesthetic predictor 映射为美学分数。
3. 模型输出除以 10 进行归一化。
4. 对视频帧求平均，再对视频求平均。

## 九、`imaging_quality`：技术画质

判断清晰度、压缩失真、噪声、模糊和整体技术质量。

1. 使用 MUSIQ-SPAQ 逐帧评分。
2. 按 `imaging_quality_preprocessing_mode` 缩放，默认使用 `longer`。
3. 对视频帧分数求平均。
4. 最终分数除以 100。

### 兼容版本

`pyiqa` 使用的 `imgaug` 与 NumPy 2.x 不兼容，镜像中应固定：

```text
numpy==1.26.4
opencv-python==4.10.0.84
opencv-python-headless==4.10.0.84
timm==0.9.16
```

## 十、`temporal_flickering`：时间闪烁

判断连续帧之间是否出现不自然的闪烁、亮度跳变或画面突变。

1. 使用 OpenCV 读取视频帧。
2. 计算相邻帧的平均绝对误差 MAE。
3. 转换为：

```text
视频分数 = (255 - 相邻帧 MAE 均值) / 255
```

相邻帧变化越小，分数越高。该指标不需要模型权重。

## 十一、`motion_smoothness`：运动平滑度

使用 AMT-S 判断视频运动是否连续自然、是否存在卡顿或不平滑。

1. 读取视频帧并进行抽取、尺寸处理。
2. 使用 AMT-S 估计相邻帧运动/插帧质量。
3. 汇总得到单视频分数。
4. 对所有视频求平均。

需要：

```text
/root/.cache/vbench/amt_model/amt-s.pth
```

## 十二、`dynamic_degree`：动态程度

判断视频是否存在明显运动以及运动幅度大小，不判断动作是否合理。

1. 使用 RAFT 计算相邻帧光流。
2. 统计光流幅度较大的区域。
3. 根据视频分辨率和帧数设置阈值。
4. 当足够多的帧超过阈值时，判定视频存在动态变化。

需要：

```text
/root/.cache/vbench/raft_model/models/raft-things.pth
```

## 十三、`camera_motion`：镜头运动一致性

判断实际镜头运动是否符合 prompt，例如：

```text
camera pans left
camera pans right
camera tilts up
camera tilts down
camera zooms in
camera zooms out
camera static
```

1. 使用 CoTracker2 跟踪视频中的网格点。
2. 根据画面边缘点的运动方向推断镜头运动类型。
3. 将预测类型与文件名中的目标类型比较。
4. 匹配得 1 分，否则得 0 分。

视频文件名必须包含镜头运动描述，例如：

```text
a city street, camera pans right-0.mp4
```

当前普通主体视频不能直接用于该指标。仅修改 `--dimension camera_motion` 不会自动补充正确的镜头运动标签。

## 十四、批量运行

同一个 Docker 环境可以批量运行多个指标，但程序按顺序运行，不应并行占用同一张 GPU。当前批量配置包含 9 个可用指标，不包含 `camera_motion`。

```bash
export VBENCH_CACHE_DIR=/root/.cache/vbench
export PYTHONUNBUFFERED=1

python /workspace/pipelines/run_evaluation.py \
  --run-dir /workspace/runs/20260722_ltx23_i2v_subject
```

结果保存到：

```text
/workspace/runs/20260722_ltx23_i2v_subject/evaluation/<dimension>/
```

总调度日志：

```text
/workspace/runs/20260722_ltx23_i2v_subject/evaluation/evaluation.log
```

批量运行时，调度器会在每个指标完成后释放 Python 垃圾和 CUDA 缓存，降低前一个模型影响后一个指标的风险。

## 十五、注意事项

- I2V 指标大多输出连续分数，不是简单的通过/失败。
- `dimension` 字段表示本次运行指定的评测维度，不是模型自动识别出的标签。
- 当前 `videos/prepared` 是公共目录；一次运行会将其中所有视频纳入当前指标。
- 需要特定 prompt 结构的指标，应先整理对应数据，不能只修改 `--dimension`。
- `pip check` 中 RetinaFace 的旧版 Torch 依赖冲突属于历史包元数据，不应通过降级 PyTorch 解决。
