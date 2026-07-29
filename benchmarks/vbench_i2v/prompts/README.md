# VBench-i2v 精选 Prompt 数据集

本文件夹从 `vbench2_i2v_full_info.json` 中抽取了 7 个类别，并按照 AI 漫剧、电影和广告宣传的实际使用场景重新筛选。样本优先覆盖人物表演、人物关系、人物与物体交互、城市/街道/建筑氛围、交通工具、夜景和镜头运动。

每个类别保留 10 条样本，难度大致覆盖低、中、高三档。难度是根据主体/场景复杂度和控制要求做的实用划分，不是官方标签。`all_unique_prompts.txt` 包含各类别中的去重 prompt；带 camera 指令的条目用于镜头运动测试。

VBench-i2v 当前官方数据提供的是 `prompt_en`，因此本文件夹保留英文 prompt。每条 prompt 对应的输入图像名称可以在原始 JSON 中通过 `prompt_en` 查找；`camera_motion` 的输入图像名称需要使用去掉相机指令后的基础场景图像。

## 文件

- `i2v_subject.txt`
- `i2v_background.txt`
- `subject_consistency.txt`
- `background_consistency.txt`
- `camera_motion.txt`
- `aesthetic_quality.txt`
- `imaging_quality.txt`

## 去重统计

使用 `all_unique_prompts.txt` 统计评测数据量，每条重复 prompt 只保留一次，共 45 条。各类别文件仍保留原样，用于按评测维度筛选；同一条 prompt 可能属于多个类别，这是原始 VBench-i2v 数据的设计。
