---
name: meshy-image-to-3d
description: Generate QuizRush Unity/Tuanjie 3D game assets from approved PNG/JPG concept images using the project Meshy image-to-3d client, download GLB output, archive Meshy task metadata safely, and optionally build runtime prefabs. Use when the user says Meshy, 图生3D, image-to-3d, GLB, AI3D, or asks how to run the project script that turns item or obstacle images into 3D models.
---

# Meshy Image to 3D

## Use the project client

Run from the QuizRush Unity project root. Do not rewrite this as ad-hoc curl.

This skill also bundles a fallback copy of the client at `scripts/meshy_client.py` and a placeholder key template at `assets/.secrets/meshy_api_key.example`. If a new computer lacks the project files, install them from the skill before running Meshy.

```bash
python3 tools/ai3d/meshy_client.py image-to-3d \
  --image <local_png_or_jpg> \
  --name <asset_slug> \
  --out Assets/QuizRush/Generated/AI3D/<asset_slug> \
  --target-polycount 12000
```

The real implemented subcommand is `image-to-3d`; ignore older docs that say `run-image-to-3d` unless the script has been verified changed.

## Preconditions

- Verify `tools/ai3d/meshy_client.py` exists; if missing, copy the bundled `scripts/meshy_client.py` into `tools/ai3d/meshy_client.py`.
- Verify Python 3 is available: `python3 --version` or `python --version`.
- Verify the source image exists and is `.png`, `.jpg`, or `.jpeg`.
- Use an approved concept/reference image; do not regenerate art unless asked.
- Read the key from `MESHY_API_KEY` or `.secrets/meshy_api_key`. Never hardcode, print, commit, or echo keys.
- For a new computer, create `QuizRush_UnityProject/.secrets/meshy_api_key` locally or set the environment variable. `.secrets/` must stay ignored by git.
- If runtime prefabs will be built, verify Unity/Tuanjie can restore `com.unity.cloud.gltfast` from `Packages/manifest.json`.
- Meshy needs network. If blocked, rerun the same script with approval instead of replacing the client.

## Slug map

| Thing | Slug |
| --- | --- |
| Coin | `coin` |
| Magnet pickup | `magnet_powerup` |
| Shield pickup | `shield_powerup` |
| Dash/boost pickup | `boost_powerup` |
| Crate obstacle | `crate_obstacle` |
| Damage barrier | `damage_barrier_obstacle` |
| Slow cone | `slow_cone_obstacle` |

## Example

```bash
python3 tools/ai3d/meshy_client.py image-to-3d \
  --image docs/V2/VisualReferences/UI/production-v4/final/items/image.png \
  --name magnet_powerup \
  --out Assets/QuizRush/Generated/AI3D/magnet_powerup \
  --target-polycount 12000
```

## New computer setup

Check these before the first Meshy run on another workstation:

```bash
python3 --version
test -f tools/ai3d/meshy_client.py
test -f .secrets/meshy_api_key || test -n "$MESHY_API_KEY"
rg -n "com\.unity\.cloud\.gltfast" Packages/manifest.json Packages/packages-lock.json
```

If the project client or local key file is missing, install the bundled skill files:

```bash
mkdir -p tools/ai3d .secrets
cp .agents/skills/meshy-image-to-3d/scripts/meshy_client.py tools/ai3d/meshy_client.py
cp .agents/skills/meshy-image-to-3d/assets/.secrets/meshy_api_key.example .secrets/meshy_api_key
```

Then replace the placeholder inside `.secrets/meshy_api_key` with the real local Meshy key, or set `MESHY_API_KEY` in the shell. Do not commit `.secrets/meshy_api_key` or real keys.


Expected output:

```text
Assets/QuizRush/Generated/AI3D/<asset_slug>/
├── source/<source-image>
├── source/meshy-task.json
├── model/<asset_slug>.glb
├── preview/
└── README.md
```

Confirm `source/meshy-task.json` redacts signed URLs as `<downloaded-and-redacted>`.

## Optional Unity prefab build

If the user wants runtime prefabs, use Unity/Tuanjie:

```text
Tools -> QuizRush -> Endless 3D -> Build Runtime Prefabs From Generated AI3D
```

This reads `Assets/QuizRush/Generated/AI3D/<slug>/model/<slug>.glb` and writes `Assets/QuizRush/Runtime/Resources/QuizRush/Endless/Prefabs/<Name>.prefab`.

Before assuming a prefab is used, inspect `Assets/QuizRush/Runtime/Scripts/QuizRushRunnerStageView.Endless.cs`. Magnet, shield, and dash may intentionally stay billboard visuals for projection readability.

## Verify before reporting

```bash
ls -lh Assets/QuizRush/Generated/AI3D/<asset_slug>/model/<asset_slug>.glb
python3 -m json.tool Assets/QuizRush/Generated/AI3D/<asset_slug>/source/meshy-task.json >/dev/null
git status --short -- Assets/QuizRush/Generated/AI3D/<asset_slug>
```

If prefabs were built:

```bash
find Assets/QuizRush/Runtime/Resources/QuizRush/Endless/Prefabs -maxdepth 1 -name "*.prefab" -print
```

## Git hygiene

- Never use `git add .`.
- Add only intended generated asset/prefab/meta files.
- Do not commit `.secrets/`, API keys, raw logs with tokens, or unredacted Meshy URLs.
- Confirm before versioning large GLB assets if the user did not explicitly ask.
