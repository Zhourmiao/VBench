# VBench-2.0 评测指标说明

本文记录当前已经调试完成的 6 个 VBench-2.0 评测指标，包括输入、采样方式、模型分工、判定逻辑和结果文件。

## 一、整体评测流程

```text
生成视频
  ↓
整理到 videos/prepared/<指标名>
  ↓
读取 selected_full_info.json
  ↓
加载本地模型权重
  ↓
对视频进行采样或逐帧分析
  ↓
得到逐视频结果
  ↓
汇总为指标总分
  ↓
保存到 evaluation/<指标名>
```

每个指标的输入主要包括：

- `videos/prepared/<dimension>`：待评测视频；
- `cases/selected_full_info.json`：prompt、辅助问题和视频路径；
- `/root/.cache/vbench2`：本地模型权重和缓存。

评测结果通常保存到：

```text
runs/<run_id>/evaluation/<dimension>/
```

常见结果字段：

- `video_path`：视频路径；
- `video_results`：单视频分数；
- `question_results`：问题、解析后的答案和原始答案；
- `qwen_results`：Qwen 的逐项判断；
- `valid`：视频是否参与平均分；
- `invalid_reason`：视频无效原因。

## 二、模型分工

| 模型或组件 | 使用指标 |
|---|---|
| LLaVA-Video-7B-Qwen2 | `Motion_Rationality`、`Mechanics`、`Motion_Order_Understanding`、`Complex_Plot` |
| Qwen2.5-7B-Instruct | `Motion_Order_Understanding`、`Complex_Plot` |
| RetinaFace + ArcFace | `Human_Identity` |
| CoTracker2 + RAFT | `Multi-View_Consistency` |

## 三、Motion_Rationality：动作合理性

### 测评内容

判断视频中的动作是否符合 prompt 描述以及现实动作逻辑。例如：

- 人是否真的在吸面条；
- 嘴是否接触面条；
- 面条数量是否发生合理变化；
- 动作结束后相关物体是否仍然存在。

### 测评流程

1. 从 `selected_full_info.json` 读取 prompt、辅助问题和视频路径。
2. 每个视频均匀采样最多 16 帧。
3. LLaVA 一次读取这组视频帧。
4. 对每个 auxiliary question 单独提问。
5. 将回答解析为 `yes`、`no` 或 `unknown`。
6. 当前调试代码要求一个视频的所有问题都回答 `yes`，该视频才得分 1。

### 计分方式

```text
视频得分 = 1，所有问题均为 yes
视频得分 = 0，只要有一个问题不是 yes

指标总分 = 通过视频数 / 有效视频数
```

注意：不是让模型对每一帧单独打分，而是将 16 帧作为一个视频片段交给 LLaVA 综合判断。

## 四、Mechanics：物理机制和物体交互合理性

### 测评内容

判断物体之间的接触、运动和物理结果是否合理。例如：

- 油是否真的接触锅；
- 锅中的油量是否增加；
- 物体是否保持存在；
- 物体交互是否符合现实物理机制。

### 测评流程

1. 每个视频均匀采样最多 32 帧。
2. LLaVA 读取采样帧。
3. 依次回答 auxiliary questions。
4. 第一个问题作为样本有效性检查。
5. 对有效视频判断其余问题是否全部为 `yes`。

### 计分方式

```text
第一个问题不是 yes
  → 视频无效，video_results = -1，不参与平均分

第一个问题是 yes 且全部问题为 yes
  → 视频得分 1

第一个问题是 yes 但存在 no
  → 视频得分 0

指标总分 = 有效视频得分总和 / 有效视频数量
```

## 五、Human_Identity：人物身份一致性

### 测评内容

判断视频中的人物身份在连续帧中是否保持一致，重点关注：

- 是否突然变成另一个人；
- 脸部是否严重变形；
- 人物身份特征是否稳定。

### 模型分工

- RetinaFace：检测视频帧中的人脸；
- ArcFace：提取人脸特征并进行相似度比较。

### 测评流程

1. 从视频中均匀采样最多 32 帧。
2. RetinaFace 检测每一帧的人脸。
3. ArcFace 提取有效人脸的特征向量。
4. 选择参考人脸，并计算其他帧与参考人脸的相似度。
5. 根据相似度阈值判断人物身份是否一致。
6. 有效帧不足 20 帧时，该视频视为无效。

### 计分方式

```text
视频分数 ≈ 身份一致的有效帧数 / 有效人脸帧数
指标总分 = 所有有效视频分数的平均值
```

## 六、Motion_Order_Understanding：动作顺序理解

### 测评内容

判断视频中的动作顺序是否符合 prompt。例如：

```text
先坐在沙发上，然后站起来做俯卧撑
```

### 测评流程

1. 对视频均匀采样帧。
2. LLaVA 读取视频并生成编号动作列表：

   ```text
   1. The person is sitting on the couch.
   2. The person stands up and does push-ups.
   ```

3. 解析 LLaVA 输出中的编号动作。
4. Qwen 将生成的动作与 ground-truth 动作逐项比较。
5. 每个动作得到 `yes` 或 `no`。

### 计分方式

当前代码通常比较两个主要动作：

```text
两个动作都匹配 → 视频得分 1
任意一个动作不匹配 → 视频得分 0
```

如果 LLaVA 没有生成有效的编号列表，则记录无效原因，不进入正常动作匹配统计。

## 七、Complex_Plot：复杂情节一致性

### 测评内容

判断多步骤情节是否连贯，重点包括：

- 情节顺序是否正确；
- 前后动作是否有逻辑关系；
- 人物和物体是否保持一致；
- 后续动作是否符合之前发生的事件。

### 测评流程

1. 每个视频均匀采样最多 64 帧。
2. LLaVA 根据视频生成编号情节或完整视频描述。
3. 如果输出格式不符合要求，代码会要求 LLaVA 重新生成描述。
4. Qwen 将生成的情节与 ground-truth 情节逐项比较。
5. 每个情节得到 `yes` 或 `no`。

### 计分方式

例如 prompt 包含 5 个情节，模型正确匹配 4 个：

```text
视频分数 = 4 / 5 = 0.8
指标总分 = 所有视频分数的平均值
```

## 八、Multi-View_Consistency：多视角一致性

### 测评内容

判断相机是否围绕主体进行合理的环绕拍摄，以及运动轨迹是否符合多视角变化要求。

### 模型分工

- CoTracker2：跟踪视频中的网格点，判断相机是否产生环绕运动；
- RAFT：计算相邻视频帧之间的光流和运动幅度；
- `PatchAutoEvaluate`：判断运动区域与主体区域的匹配情况。

### 测评流程

1. CoTracker2 对视频中的点进行跟踪。
2. 根据画面边缘点的运动方向判断是否存在相机环绕运动。
3. 如果没有检测到环绕运动，视频被标记为无效。
4. 对有效视频使用 RAFT 计算相邻帧光流。
5. 计算运动幅度和运动区域匹配度。
6. 综合得到视频分数。

### 计分方式

```text
未检测到相机环绕运动
  → valid = false
  → invalid_reason = camera orbit not detected

检测到相机环绕运动
  → 根据光流幅度和区域匹配结果计算视频分数

指标总分 = 有效视频分数的平均值
```

如果所有视频都没有检测到环绕运动，当前代码返回 `0.0`，同时保留逐视频诊断信息。这种 `0.0` 表示没有有效环绕运动样本，不等同于有效样本的正常零分。

## 九、当前完成状态

已完成：

- `Motion_Rationality`
- `Mechanics`
- `Human_Identity`
- `Motion_Order_Understanding`
- `Complex_Plot`
- `Multi-View_Consistency`

暂未完成：

- `Human_Anatomy`

`Human_Anatomy` 依赖 YOLO-World、MMCV、MMDetection 和 SimMIM 异常检测模型，与当前 LLaVA 评测环境存在版本冲突，建议使用独立 Docker 容器或独立 Conda 环境。
