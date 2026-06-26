# Meshy Image to 3D Skill

Codex skill for generating QuizRush / Unity / Tuanjie 3D game assets from approved PNG/JPG concept images through Meshy `image-to-3d`.

## What it does

- Uses the bundled `scripts/meshy_client.py` Meshy client.
- Converts local PNG/JPG images to Meshy image-to-3D tasks.
- Downloads GLB output into `Assets/QuizRush/Generated/AI3D/<asset_slug>/model/`.
- Archives Meshy task metadata with signed URLs redacted.
- Documents optional Unity/Tuanjie prefab build steps.

## Install into a project

Copy this folder into a project skill directory, for example:

```text
<project>/.agents/skills/meshy-image-to-3d/
```

Then invoke it in Codex with:

```text
$meshy-image-to-3d 用这张图生3D
```

## New workstation setup

From the Unity project root:

```bash
mkdir -p tools/ai3d .secrets
cp .agents/skills/meshy-image-to-3d/scripts/meshy_client.py tools/ai3d/meshy_client.py
cp .agents/skills/meshy-image-to-3d/assets/.secrets/meshy_api_key.example .secrets/meshy_api_key
```

Edit `.secrets/meshy_api_key` and put your real Meshy API key inside, or set `MESHY_API_KEY` in your shell.

Never commit real API keys.

## Example command

```bash
python3 tools/ai3d/meshy_client.py image-to-3d \
  --image docs/V2/VisualReferences/UI/production-v4/final/items/image.png \
  --name magnet_powerup \
  --out Assets/QuizRush/Generated/AI3D/magnet_powerup \
  --target-polycount 12000
```


## Batch parallel generation

Generate many images in parallel from a directory:

```bash
python3 tools/ai3d/meshy_client.py batch-image-to-3d \
  --image-dir docs/V2/VisualReferences/AI3DConcepts \
  --out-root Assets/QuizRush/Generated/AI3D \
  --concurrency 4
```

Or use a manifest for stable names:

```json
{
  "assets": [
    {"image": "docs/V2/VisualReferences/AI3DConcepts/coin.png", "name": "coin"},
    {"image": "docs/V2/VisualReferences/AI3DConcepts/magnet.png", "name": "magnet_powerup"}
  ]
}
```

Meshy queue concurrency is account-plan dependent. Use `--concurrency 4` by default; known published limits are Pro 10, Studio 20, Enterprise 50 by default/customizable.

## Repository contents

```text
SKILL.md
agents/openai.yaml
scripts/meshy_client.py
assets/.secrets/meshy_api_key.example
```

## Security notes

- `meshy_api_key.example` is a placeholder only.
- Do not commit `.secrets/meshy_api_key` with a real key.
- The client redacts Meshy signed download URLs before archiving `meshy-task.json`.
