# Meshy 图生 3D Skill

[中文](./README.zh-CN.md) | [English](./README.en.md)

这是一个 Codex skill，用于把已确认的 PNG/JPG 概念图，通过 Meshy `image-to-3d` 生成 Unity / Tuanjie 游戏项目可用的 GLB/FBX 3D 资产。

## 功能

- 使用内置的 `scripts/meshy_client.py` Meshy 客户端。
- 将本地 PNG/JPG 图片提交为 Meshy image-to-3D 任务。
- 将 GLB/FBX 下载到 `Assets/QuizRush/Generated/AI3D/<asset_slug>/model/`。
- 归档 Meshy 任务元数据，并自动脱敏签名下载 URL。
- 支持可选的 Unity/Tuanjie Runtime Prefab 构建说明。
- 支持批量并行生成、断点续跑、429 自动退避、manifest、batch summary、以及 `--format glb|fbx`。

## 安装到项目

把本仓库文件夹复制到项目 skill 目录，例如：

```text
<project>/.agents/skills/meshy-image-to-3d/
```

然后在 Codex 中这样调用：

```text
$meshy-image-to-3d 用这张图生3D
```

## 新电脑初始化

在 Unity 项目根目录执行：

```bash
python3 .agents/skills/meshy-image-to-3d/scripts/meshy_client.py install-project \
  --project-root . \
  --with-key-template
```

然后编辑：

```text
.secrets/meshy_api_key
```

把里面的占位内容替换成真实 Meshy API Key。也可以不写文件，改用 shell 环境变量：

```bash
export MESHY_API_KEY="msy_xxx"
```

永远不要提交真实 API Key。

## 单张图片生成

```bash
python3 tools/ai3d/meshy_client.py image-to-3d \
  --image docs/V2/VisualReferences/UI/production-v4/final/items/image.png \
  --name magnet_powerup \
  --out Assets/QuizRush/Generated/AI3D/magnet_powerup \
  --target-polycount 12000 \
  --format glb
```

输出结构：

```text
Assets/QuizRush/Generated/AI3D/<asset_slug>/
├── source/<source-image>
├── source/meshy-task.json
├── model/<asset_slug>.<format>
├── preview/
└── README.md
```

## 人物 FBX 生成

人物如果要进入“重拓扑 + 绑定骨骼 + 复用当前 Runner 动画”流程，直接请求 FBX，并尽量让 Meshy 产出 A-pose/T-pose 和四边面拓扑：

```bash
python3 tools/ai3d/meshy_client.py image-to-3d \
  --image docs/V2/VisualReferences/female-runner-pink-ponytail-v2/female_runner_pink_ponytail_01.png \
  --name female_runner_pink_ponytail_01 \
  --out Assets/QuizRush/Generated/AI3D/female_runner_pink_ponytail_01 \
  --target-polycount 30000 \
  --format fbx \
  --topology quad \
  --pose-mode a-pose
```

推荐规则：道具/障碍物用 `--format glb`；人物/需要复用 Animator、Avatar、骨骼动画的资产用 `--format fbx`。Meshy 支持 `glb`、`obj`、`fbx`、`stl`、`usdz`、`3mf`。

## 人物 Meshy 自动绑骨

人物主流程是 Meshy 生模型、贴图和骨骼；旧角色只复用跑步动作/Animator，不做旧皮肤权重迁移。优先用 image-to-3D 输出的 `source/meshy-task.json` 作为输入：

```bash
python3 tools/ai3d/meshy_client.py rig-character \
  --task-json Assets/QuizRush/Generated/AI3D/female_runner_pink_ponytail_01/source/meshy-task.json \
  --name female_runner_pink_ponytail_01 \
  --out Assets/QuizRush/Generated/AI3D/female_runner_pink_ponytail_01/rigged \
  --height-meters 1.35
```

输出：

```text
Assets/QuizRush/Generated/AI3D/<asset_slug>/rigged/
├── model/<asset_slug>_rigged.fbx
├── textures/texture_0.png
├── source/rigging-task.json
└── README.md
```

然后在 Unity/Tuanjie 执行：

```text
Tools -> QuizRush -> Wire Meshy Rigged Female Runner
```

该菜单会把 rigged FBX 复制到 `Assets/QuizRush/Generated/Runner/Current/FemaleRunnerPinkPonytail.fbx`，设置 Humanoid，创建 `FemaleRunnerPinkPonytailController.controller`，复用 `HunyuanRunner.fbx` 里的跑步动作，并覆盖 `Assets/QuizRush/Generated/Runner/Current/AnimatedCharacter.prefab`。

## 批量并行生成

从图片目录批量生成：

```bash
python3 tools/ai3d/meshy_client.py batch-image-to-3d \
  --image-dir docs/V2/VisualReferences/AI3DConcepts \
  --out-root Assets/QuizRush/Generated/AI3D \
  --concurrency 4 \
  --skip-existing \
  --summary batch-summary.json
```

或者使用 manifest 稳定命名：

```json
{
  "assets": [
    {"image": "docs/V2/VisualReferences/AI3DConcepts/coin.png", "name": "coin"},
    {"image": "docs/V2/VisualReferences/AI3DConcepts/magnet.png", "name": "magnet_powerup", "format": "glb"}
  ]
}
```

运行：

```bash
python3 tools/ai3d/meshy_client.py batch-image-to-3d \
  --manifest batch.json \
  --out-root Assets/QuizRush/Generated/AI3D \
  --concurrency 4 \
  --skip-existing \
  --summary batch-summary.json
```

Manifest 可为人物单独覆盖格式：

```json
{
  "assets": [
    {"image": "docs/V2/VisualReferences/AI3DConcepts/coin.png", "name": "coin", "format": "glb"},
    {"image": "docs/V2/VisualReferences/female-runner-pink-ponytail-v2/female_runner_pink_ponytail_01.png", "name": "female_runner_pink_ponytail_01", "format": "fbx", "target_polycount": 30000, "topology": "quad", "pose_mode": "a-pose"}
  ]
}
```

## Manifest 自动生成

```bash
python3 tools/ai3d/meshy_client.py make-manifest \
  --image-dir docs/V2/VisualReferences/AI3DConcepts \
  --out batch.json
```

生成后建议先人工检查 `name`，避免资产名不稳定。

## 并发建议

Meshy 队列并发受账号档位限制。保守默认：

```bash
--concurrency 4
```

已知官方档位：

| 档位 | 队列并发上限 | 建议值 |
| --- | ---: | ---: |
| Pro | 10 | 6-8 |
| Studio | 20 | 10-16 |
| Enterprise | 默认 50，可定制 | 20-30 起测 |

如果触发 `429 / NoMoreConcurrentTasks / RateLimitExceeded`，脚本会按默认参数自动指数退避：

```bash
--rate-limit-retries 5
--rate-limit-backoff 30
```

## 断点续跑和安全

- `--skip-existing`：已有 `model/<name>.<format>` 时跳过，避免重复烧额度。
- `--summary batch-summary.json`：记录成功、跳过、失败、模型路径、task id 和错误。
- `make-manifest`：先生成可编辑 manifest，再消耗 Meshy 额度。
- `install-project`：把 skill 内置脚本同步到 Unity 项目的 `tools/ai3d/meshy_client.py`。
- Meshy 签名下载 URL 会在 `meshy-task.json` 和 `rigging-task.json` 中脱敏为 `<downloaded-and-redacted>`。

## 仓库内容

```text
SKILL.md
agents/openai.yaml
scripts/meshy_client.py
assets/.secrets/meshy_api_key.example
README.md
README.zh-CN.md
README.en.md
```

## 安全说明

- `meshy_api_key.example` 只是占位模板。
- 不要提交 `.secrets/meshy_api_key` 真实密钥。
- 不要提交包含 Token / 签名 URL 的日志。
