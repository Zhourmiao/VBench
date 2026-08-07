## 1. 实验背景

本实验采用 VBench 2.0 语义理解类指标，并复用 VBench/I2V 中不依赖输入图片的 7 个视频质量指标，对 Kling、Pangu 和 LTX-2.3 三个 Text-to-Video（T2V）模型进行评测。

分数范围为 0 到 1，分数越高表示对应能力越强。本轮三个模型均覆盖 17 个汇总指标。

## 2. 数据集与评测范围

测试 Prompt 来自 VBench 2.0 T2V benchmark，模型生成阶段使用英文 Prompt。每条 case 保留原始展示字段和英文评测字段：

- `prompt_input`：原始或展示用 Prompt；
- `prompt_eval_en`：英文评测 Prompt；
- `prompt` / `effective_parameters.prompt`：实际提交给生成模型的 Prompt。

本轮汇总包含以下 10 个 VBench 2.0 语义维度和 7 个视频-only 质量维度：

```text
VBench 2.0：Complex_Landscape、Complex_Plot、Composition、
Dynamic_Spatial_Relationship、Human_Identity、Human_Interaction、
Mechanics、Motion_Order_Understanding、Motion_Rationality、
Multi-View_Consistency

视频-only：aesthetic_quality、background_consistency、dynamic_degree、
imaging_quality、motion_smoothness、subject_consistency、
temporal_flickering
```

当前运行目录中的 case 规模为：Kling 64 条，LTX-2.3 192 条（包含多次采样记录）；Pangu  192 条（包含多次采样记录）。Kling 每条 Prompt 生成一个样本，Pangu 和 LTX-2.3 使用多个固定随机种子，以降低单次采样随机性影响。

## 3. 评测方法

```text
英文 Prompt
    ↓
T2V 模型生成视频
    ↓
视频格式和完整性检查
    ↓
VBench 2.0 语义指标评测
    ↓
视频-only 指标评测
    ↓
按维度汇总模型得分
```

结果由以下命令汇总：

```bash
python pipelines/aggregate_scores.py --run-dir runs/20260729_pangu_t2v
python pipelines/aggregate_scores.py --run-dir runs/20260729_kling_t2v
python pipelines/aggregate_scores.py --run-dir runs/20260729_ltx23_t2v
```

## 4. 各评测维度的具体评测方式

### 4.1 统一的 `yes/no` 判定规则

语义理解类指标由视频理解模型读取均匀采样的视频帧，并根据 Prompt 生成一个或多个判断问题。回答通常要求只输出 `yes` 或 `no`；代码会解析回答中的第一个有效 `yes/no`。

例如，一条包含四个辅助问题的 case 可以抽象为：

```text
问题 1：视频中是否发生了事件 A？ → yes
问题 2：视频中是否发生了事件 B？ → yes
问题 3：事件 A 与事件 B 的顺序是否正确？ → yes
问题 4：相关人物和物体是否保持一致？ → yes
```

常见计分规则：

```text
全部回答 yes → 视频得分 1
有任意一个回答 no/unknown → 视频得分 0
按通过题目数计分 → 视频得分 = yes 数量 / 问题总数
指标得分 → 所有有效视频得分的平均值
```

其中，“四个问题”只是说明计分逻辑的示例；实际问题数量由该维度的官方 `auxiliary_info` 和具体 Prompt 决定，并不固定为四个。

### 4.2 VBench 2.0 语义理解维度

| 维度                             | 具体评测方式                                                          | 单视频判定/计分                                                                        | 主要评测组件               |
| ------------------------------ | --------------------------------------------------------------- | ------------------------------------------------------------------------------- | -------------------- |
| `Complex_Landscape`            | LLaVA 先描述视频中的复杂场景，再由 Qwen 将描述与 Prompt 中的场景要素逐项比较，回答每个要素是否出现。    | 按回答 `yes` 的场景要素数占比计分；例如 4 个要素中 3 个为 `yes`，视频分数为 0.75。                           | LLaVA-Video + Qwen   |
| `Complex_Plot`                 | LLaVA 生成编号的事件/情节列表，必要时重新生成或由 Qwen 整理；Qwen 逐项比较 Prompt 情节与视频情节。  | 按匹配成功的情节数占比计分；不是简单判断画面是否“看起来相似”。                                                | LLaVA-Video + Qwen   |
| `Composition`                  | 对“视频中是否始终只有一个生物”和 Prompt 中的组成要素分别提问，例如“是否包含鹰的翅膀”“是否包含狮子”。       | 根据 case 的 `judge` 配置：可按 `yes` 数量比例计分，也可要求所有组成问题均为 `yes` 才得 1。                   | LLaVA-Video          |
| `Dynamic_Spatial_Relationship` | 对视频帧中的动态空间关系逐项提问，例如物体相对位置、移动方向或空间关系是否符合 Prompt。                 | 逐题解析 `yes/no`；该实现要求一条 case 的所有辅助问题为 `yes` 才记 1。                                 | LLaVA-Video          |
| `Human_Identity`               | 从视频均匀采样最多 32 帧；RetinaFace 检测人脸，ArcFace 提取人脸特征，并与跟踪到的参考身份计算相似度。  | 视频分数 = 身份一致的有效人脸帧数 / 有效人脸帧数；有效帧少于 20 帧的视频不参与平均。                                 | RetinaFace + ArcFace |
| `Human_Interaction`            | LLaVA 分别生成“人与人交互描述”和详细视频描述；Qwen 检查交互是否符合 Prompt，并检查描述中是否确实包含多人。 | 两个判断都为 `yes` → 视频得分 1；否则为 0。                                                    | LLaVA-Video + Qwen   |
| `Mechanics`                    | 对物体接触、运动结果和物理机制逐项提问，例如是否发生接触、物体状态是否改变、结果是否符合物理规律。               | 第一个问题是有效性检查；第一个为 `yes` 且其余问题全部为 `yes` → 1；有效但有 `no` → 0；第一个不是 `yes` → 无效，不计入平均。 | LLaVA-Video          |
| `Motion_Order_Understanding`   | LLaVA 将视频整理为编号动作列表，例如“1. 先坐下；2. 再站起并俯卧撑”；Qwen 逐项检查动作是否发生且顺序正确。  | 当前实现主要检查两个动作；两个问题都为 `yes` → 1，否则 → 0。无法生成有效编号列表时记录为无效。                          | LLaVA-Video + Qwen   |
| `Motion_Rationality`           | 根据 Prompt 的辅助问题检查动作是否真实发生、动作关系是否合理、接触和状态变化是否符合现实。               | 所有辅助问题均为 `yes` → 1；任意一个为 `no/unknown` → 0。                                      | LLaVA-Video          |
| `Multi-View_Consistency`       | CoTracker2 跟踪网格点并判断是否存在环绕相机运动；对有效视频再用 RAFT 计算光流、运动幅度和运动区域匹配度。   | 未检测到所需环绕运动 → 无效；检测到后按运动幅度与区域匹配度计算连续分数，再对有效视频求平均。                                | CoTracker2 + RAFT    |

### 4.3 视频-only 质量维度

以下维度不向模型提出四个 `yes/no` 问题，而是直接对视频帧或相邻帧计算连续质量分数。分数越高表示对应质量越好。

| 维度                       | 具体评测方式                                                      | 单视频分数/判定                                       | 主要组件                                      |
| ------------------------ | ----------------------------------------------------------- | ---------------------------------------------- | ----------------------------------------- |
| `aesthetic_quality`      | 对视频帧提取 CLIP ViT-L/14 特征，用 LAION aesthetic predictor 预测美学分数。 | 帧分数平均后归一化到 0–1，再对视频求平均。                        | CLIP ViT-L/14 + LAION aesthetic predictor |
| `background_consistency` | 用 CLIP ViT-B/32 比较当前帧与前一帧、第一帧的背景/整体特征相似度。                   | 对非负余弦相似度求平均；越高表示背景越稳定。                         | CLIP ViT-B/32                             |
| `dynamic_degree`         | 用 RAFT 计算相邻帧光流，统计运动幅度较大的区域和帧。                               | 根据光流幅度归一化得到连续分数；只衡量运动多少，不判断动作是否合理。             | RAFT                                      |
| `imaging_quality`        | 用 MUSIQ-SPAQ 对视频帧进行技术画质评价，关注清晰度、噪声、压缩和失真。                   | 帧质量分数平均后除以 100，归一化到 0–1。                       | MUSIQ-SPAQ                                |
| `motion_smoothness`      | 用 AMT-S 评估相邻帧运动/插帧质量，检查运动是否连续平滑。                            | 对帧级结果求平均；越高表示卡顿和不连续越少。                         | AMT-S                                     |
| `subject_consistency`    | 用 DINO 提取每帧主体特征，同时与第一帧和前一帧比较。                               | 当前帧分数为两种相似度的平均值，再对视频帧求平均。                      | DINO ViT-B/16                             |
| `temporal_flickering`    | 用 OpenCV 计算相邻帧的平均绝对误差（MAE）。                                 | `视频分数 = (255 - 相邻帧 MAE 均值) / 255`；越高表示闪烁和突变越少。 | OpenCV                                    |

## 5. 最新评测结果

### 5.1 综合得分

| 汇总项                     |  Pangu |      Kling |    LTX-2.3 |
| ----------------------- | -----: | ---------: | ---------: |
| VBench 2.0 已评测维度平均分     | 0.5036 | **0.6131** |     0.4367 |
| 视频-only 七维平均分           | 0.8171 | **0.8412** |     0.8357 |
| 所有可用指标平均分               | 0.6327 | **0.7070** |     0.6010 |
| `official_vbench2_mean` | 0.6128 | **0.6782** |     0.5458 |

按所有可用指标平均分排名：

```text
Kling > Pangu > LTX-2.3
```

“所有可用指标平均分”不应视为完整官方 VBench 2.0 总分。

### 5.2 各维度得分

| 指标                             |      Pangu |      Kling |    LTX-2.3 |
| ------------------------------ | ---------: | ---------: | ---------: |
| `Complex_Landscape`            |     0.2190 |     0.2286 | **0.2381** |
| `Complex_Plot`                 |     0.2133 | **0.4000** |     0.1067 |
| `Composition`                  | **0.8667** |     0.8000 | **0.8667** |
| `Dynamic_Spatial_Relationship` | **0.4667** |     0.4000 |     0.2667 |
| `Human_Identity`               | **0.8409** |     0.6396 |     0.7147 |
| `Human_Interaction`            |     0.5714 | **0.8571** |     0.5714 |
| `Mechanics`                    |     0.7059 | **0.8333** |     0.7500 |
| `Motion_Order_Understanding`   |     0.3333 | **0.4286** |     0.1905 |
| `Motion_Rationality`           |     0.4667 | **0.6000** |     0.3333 |
| `Multi-View_Consistency`       |     0.3516 | **0.9442** |     0.3291 |
| `aesthetic_quality`            | **0.5607** |     0.5255 |     0.5447 |
| `background_consistency`       | **0.9530** |     0.9146 |     0.9435 |
| `dynamic_degree`               |     0.6008 | **0.9688** |     0.7917 |
| `imaging_quality`              | **0.6964** |     0.6685 |     0.6853 |
| `motion_smoothness`            | **0.9944** |     0.9885 |     0.9901 |
| `subject_consistency`          | **0.9285** |     0.8525 |     0.9175 |
| `temporal_flickering`          | **0.9859** |     0.9699 |     0.9768 |

### 5.3 分组得分

| 分组 | Pangu | Kling | LTX-2.3 |
|---|---:|---:|---:|
| creativity | 0.8667 | 0.8000 | **0.8667** |
| commonsense | 0.4667 | **0.6000** | 0.3333 |
| controllability | 0.3608 | **0.4629** | 0.2747 |
| human_fidelity | **0.8409** | 0.6396 | 0.7147 |
| physics | 0.5288 | **0.8888** | 0.5395 |

以上分组分数仅基于本轮已评测维度计算。`official_vbench2_mean` 来自当前汇总器对可用官方维度的计算，不能替代完整官方 VBench 2.0 总分。

## 6. 结果分析

### 6.1 Kling

Kling 的所有可用指标平均分、视频-only 七维平均分和 `official_vbench2_mean` 均为三者最高。主要优势包括：

- `Multi-View_Consistency`：0.9442；
- `Human_Interaction`：0.8571；
- `Mechanics`：0.8333；
- `dynamic_degree`：0.9688；
- `Complex_Plot`：0.4000。

Kling 在视角变化、人物交互、物理动作和动态表现方面优势明显。相对不足是 `subject_consistency`（0.8525）、`temporal_flickering`（0.9699）和 `imaging_quality`（0.6685）低于至少一个对比模型。

### 6.2 Pangu

Pangu 在人物与主体稳定性方面表现最好：

- `Human_Identity`：0.8409；
- `subject_consistency`：0.9285；
- `background_consistency`：0.9530；
- `motion_smoothness`：0.9944；
- `temporal_flickering`：0.9859。

Pangu 更适合人物身份、主体外观和背景连续性要求较高的任务，并在 `Human_Identity`（0.8409）、`background_consistency`（0.9530）、`subject_consistency`（0.9285）、`motion_smoothness`（0.9944）和 `temporal_flickering`（0.9859）上领先。相对不足是 `Complex_Plot`（0.2133）、`Multi-View_Consistency`（0.3516）和 `dynamic_degree`（0.6008）。

### 6.3 LTX-2.3

LTX-2.3 的视频-only 七维平均分为 0.8357，排名第二，并在以下指标上取得最高或并列最高：

- `Complex_Landscape`：0.2381；
- `Composition`：0.8667（与 Pangu 并列）。

其 `aesthetic_quality` 为 0.5447，高于 Kling 的 0.5255，但低于 Pangu 的 0.5607。

这表明 LTX-2.3 在复杂场景、构图和美学质量方面较强，但视频-only 综合分略低于 Kling。其主要短板是 `Complex_Plot`（0.1067）、`Motion_Order_Understanding`（0.1905）和 `Motion_Rationality`（0.3333）。

## 7. 结论

最新结果显示，三个模型仍呈现清晰的能力侧重：

- **Kling**：综合能力最强，在复杂情节、人物交互、物理规律、多视角一致性和动态表现方面领先；
- **Pangu**：人物身份、主体一致性、背景稳定性和时序稳定性突出；
- **LTX-2.3**：视频-only 质量平均分排名第二，在复杂场景和构图方面具有优势，但复杂情节和动作顺序规划相对较弱。

总体来看，T2V 模型仍存在“语义规划能力”和“视频视觉质量”之间的能力分化。后续优化应重点关注复杂文本理解、动作顺序规划、多视角一致性和主体长期保持能力。
