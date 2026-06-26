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
python3 .agents/skills/meshy-image-to-3d/scripts/meshy_client.py install-project \
  --project-root . \
  --with-key-template
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


## Batch parallel generation

Use `batch-image-to-3d` when generating several approved item/obstacle images. Default to `--concurrency 4` unless the user specifies a plan limit. Meshy published queue concurrency limits are plan-dependent: Pro 10, Studio 20, Enterprise 50 by default/customizable. Stay below the account limit; if unsure, use 4. Always prefer `--skip-existing` for resumable reruns and keep the default 429 exponential backoff unless debugging.

Directory mode:

```bash
python3 tools/ai3d/meshy_client.py batch-image-to-3d \
  --image-dir docs/V2/VisualReferences/AI3DConcepts \
  --out-root Assets/QuizRush/Generated/AI3D \
  --concurrency 4 \
  --target-polycount 12000 \
  --skip-existing
```

Manifest mode gives stable names and per-asset overrides:

```json
{
  "assets": [
    {"image": "docs/V2/VisualReferences/AI3DConcepts/coin.png", "name": "coin"},
    {"image": "docs/V2/VisualReferences/AI3DConcepts/magnet.png", "name": "magnet_powerup"}
  ]
}
```

```bash
python3 tools/ai3d/meshy_client.py batch-image-to-3d \
  --manifest docs/V2/VisualReferences/AI3DConcepts/batch.json \
  --out-root Assets/QuizRush/Generated/AI3D \
  --concurrency 4 \
  --skip-existing \
  --summary batch-summary.json
```

Generate a manifest first when names/paths matter:

```bash
python3 tools/ai3d/meshy_client.py make-manifest \
  --image-dir docs/V2/VisualReferences/AI3DConcepts \
  --out docs/V2/VisualReferences/AI3DConcepts/batch.json
```

Run `--dry-run` before spending Meshy credits.

## Optional Unity prefab build

If the user wants runtime prefabs, use Unity/Tuanjie:

```text
Tools -> QuizRush -> Endless 3D -> Build Runtime Prefabs From Generated AI3D
```

This reads `Assets/QuizRush/Generated/AI3D/<slug>/model/<slug>.glb` and writes `Assets/QuizRush/Runtime/Resources/QuizRush/Endless/Prefabs/<Name>.prefab`.

Before assuming a prefab is used, inspect `Assets/QuizRush/Runtime/Scripts/QuizRushRunnerStageView.Endless.cs`. Magnet, shield, and dash may intentionally stay billboard visuals for projection readability.

## Five built-in safeguards

1. `--skip-existing` prevents spending credits again when `model/<name>.glb` already exists.
2. `--rate-limit-retries` and `--rate-limit-backoff` retry Meshy `429` / `NoMoreConcurrentTasks` / `RateLimitExceeded` with exponential backoff.
3. `install-project` syncs the bundled client into `tools/ai3d/meshy_client.py` and can copy the key template locally.
4. `make-manifest` creates editable batch manifests from image directories.
5. `--summary batch-summary.json` records succeeded/skipped/failed items for reruns and review.

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
