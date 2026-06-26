#!/usr/bin/env python3
"""Meshy API helper for QuizRush AI 3D assets.

Usage:
  export MESHY_API_KEY="msy_..."
  python3 tools/ai3d/meshy_client.py image-to-3d \
    --image docs/V2/VisualReferences/AI3DConcepts/coin.png \
    --name coin \
    --out Assets/QuizRush/Generated/AI3D/coin \
    --target-polycount 12000
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import shutil
import sys
import time
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

MESHY_BASE_URL = "https://api.meshy.ai"
IMAGE_TO_3D_ENDPOINT = f"{MESHY_BASE_URL}/openapi/v1/image-to-3d"
DEFAULT_POLL_INTERVAL_SECONDS = 10
DEFAULT_TIMEOUT_SECONDS = 60


class MeshyError(RuntimeError):
    pass


def require_api_key(api_key_file: Optional[str] = None) -> str:
    api_key = os.environ.get("MESHY_API_KEY", "").strip()

    if not api_key and api_key_file:
        key_path = Path(api_key_file).expanduser()
        if key_path.exists():
            api_key = key_path.read_text(encoding="utf-8").strip()

    if not api_key:
        raise MeshyError(
            "MESHY_API_KEY is not set. Set it in your shell or put it in .secrets/meshy_api_key."
        )
    return api_key


def json_request(method: str, url: str, api_key: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    body = None
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }

    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise MeshyError(f"Meshy API HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise MeshyError(f"Meshy API network error: {exc}") from exc


def file_to_data_uri(image_path: Path) -> str:
    if not image_path.exists():
        raise MeshyError(f"Image does not exist: {image_path}")
    if not image_path.is_file():
        raise MeshyError(f"Image path is not a file: {image_path}")

    mime_type, _ = mimetypes.guess_type(str(image_path))
    if mime_type not in {"image/png", "image/jpeg"}:
        raise MeshyError(f"Meshy supports .png/.jpg/.jpeg; got {mime_type or 'unknown'}: {image_path}")

    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def safe_write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def create_image_to_3d_task(
    api_key: str,
    image_data_uri: str,
    target_polycount: int,
    enable_pbr: bool,
    should_remesh: bool,
    model_type: str,
) -> str:
    payload: Dict[str, Any] = {
        "image_url": image_data_uri,
        "ai_model": "latest",
        "model_type": model_type,
        "should_texture": True,
        "enable_pbr": enable_pbr,
        "should_remesh": should_remesh,
        "target_polycount": target_polycount,
        "target_formats": ["glb"],
        "multi_view_thumbnails": True,
        "auto_size": True,
        "origin_at": "bottom",
    }

    response = json_request("POST", IMAGE_TO_3D_ENDPOINT, api_key, payload)
    task_id = response.get("result")
    if not task_id:
        raise MeshyError(f"Meshy response missing result task id: {response}")
    return str(task_id)


def retrieve_image_to_3d_task(api_key: str, task_id: str) -> Dict[str, Any]:
    return json_request("GET", f"{IMAGE_TO_3D_ENDPOINT}/{task_id}", api_key)


def poll_task(api_key: str, task_id: str, interval_seconds: int, max_wait_seconds: int) -> Dict[str, Any]:
    deadline = time.time() + max_wait_seconds
    last_status = ""

    while True:
        task = retrieve_image_to_3d_task(api_key, task_id)
        status = str(task.get("status", "UNKNOWN"))
        progress = task.get("progress", 0)

        if status != last_status or status in {"PENDING", "IN_PROGRESS"}:
            print(f"[meshy] task={task_id} status={status} progress={progress}%", flush=True)
            last_status = status

        if status == "SUCCEEDED":
            return task

        if status in {"FAILED", "CANCELED", "EXPIRED"}:
            raise MeshyError(f"Meshy task ended with status={status}: {task.get('task_error')}")

        if time.time() >= deadline:
            raise MeshyError(f"Timed out waiting for Meshy task {task_id} after {max_wait_seconds}s")

        time.sleep(interval_seconds)


def download_url(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "QuizRush-MeshyClient/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            dest.write_bytes(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise MeshyError(f"Download HTTP {exc.code} for {dest.name}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise MeshyError(f"Download network error for {dest.name}: {exc}") from exc


def redact_task_for_archive(task: Dict[str, Any]) -> Dict[str, Any]:
    """Archive useful task metadata without preserving signed asset URLs long-term."""
    redacted = dict(task)
    if "model_url" in redacted:
        redacted["model_url"] = "<downloaded-and-redacted>"
    if "model_urls" in redacted:
        redacted["model_urls"] = {key: "<downloaded-and-redacted>" for key in redacted["model_urls"].keys()}
    if "thumbnail_url" in redacted:
        redacted["thumbnail_url"] = "<downloaded-and-redacted>"
    if "thumbnail_urls" in redacted and isinstance(redacted["thumbnail_urls"], dict):
        redacted["thumbnail_urls"] = {key: "<downloaded-and-redacted>" for key in redacted["thumbnail_urls"].keys()}
    if "texture_urls" in redacted:
        redacted["texture_urls"] = "<downloaded-and-redacted>"
    return redacted


def write_asset_readme(out_dir: Path, asset_name: str, source_image: Path, task_id: str, target_polycount: int) -> None:
    readme = f"""# {asset_name} Meshy AI 3D Asset

Generated by `tools/ai3d/meshy_client.py`.

## Source

- Source image: `source/{source_image.name}`
- Meshy task id: `{task_id}`
- Target polycount: `{target_polycount}`
- Target format: `glb`

## Output

- Model: `model/{asset_name}.glb`
- Task archive: `source/meshy-task.json`
- Preview images: `preview/`

## Unity checklist

- Import GLB in Unity/Tuanjie.
- Check scale and pivot.
- Use simple collider/trigger, not high-poly MeshCollider.
- Create runtime prefab only after visual/performance acceptance.
"""
    (out_dir / "README.md").write_text(readme, encoding="utf-8")


def run_image_to_3d(args: argparse.Namespace) -> int:
    api_key = require_api_key(args.api_key_file)
    image_path = Path(args.image).resolve()
    out_dir = Path(args.out)
    asset_name = args.name.strip()
    if not asset_name:
        raise MeshyError("--name must not be empty")

    source_dir = out_dir / "source"
    model_dir = out_dir / "model"
    preview_dir = out_dir / "preview"
    source_dir.mkdir(parents=True, exist_ok=True)
    model_dir.mkdir(parents=True, exist_ok=True)
    preview_dir.mkdir(parents=True, exist_ok=True)

    source_copy = source_dir / image_path.name
    if image_path != source_copy.resolve():
        shutil.copy2(image_path, source_copy)

    print(f"[meshy] creating image-to-3d task for {asset_name}", flush=True)
    task_id = create_image_to_3d_task(
        api_key=api_key,
        image_data_uri=file_to_data_uri(image_path),
        target_polycount=args.target_polycount,
        enable_pbr=not args.no_pbr,
        should_remesh=not args.no_remesh,
        model_type=args.model_type,
    )
    print(f"[meshy] created task {task_id}", flush=True)

    task = poll_task(
        api_key=api_key,
        task_id=task_id,
        interval_seconds=args.poll_interval,
        max_wait_seconds=args.max_wait,
    )

    model_urls = task.get("model_urls") or {}
    glb_url = model_urls.get("glb")
    if not glb_url:
        raise MeshyError(f"Succeeded task has no GLB URL: {task}")

    glb_path = model_dir / f"{asset_name}.glb"
    print(f"[meshy] downloading GLB -> {glb_path}", flush=True)
    download_url(str(glb_url), glb_path)

    thumbnail_url = task.get("thumbnail_url")
    if thumbnail_url:
        print("[meshy] downloading preview thumbnail", flush=True)
        download_url(str(thumbnail_url), preview_dir / "preview.png")

    thumbnail_urls = task.get("thumbnail_urls") or {}
    if isinstance(thumbnail_urls, dict):
        for view_name, view_url in thumbnail_urls.items():
            if view_url:
                print(f"[meshy] downloading {view_name} thumbnail", flush=True)
                download_url(str(view_url), preview_dir / f"{view_name}.png")

    safe_write_json(source_dir / "meshy-task.json", redact_task_for_archive(task))
    write_asset_readme(out_dir, asset_name, image_path, task_id, args.target_polycount)

    print("[meshy] done", flush=True)
    print(f"[meshy] model: {glb_path}", flush=True)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="QuizRush Meshy AI 3D asset client")
    subparsers = parser.add_subparsers(dest="command", required=True)

    image_parser = subparsers.add_parser("image-to-3d", help="Create Meshy image-to-3d task and download GLB")
    image_parser.add_argument("--image", required=True, help="Local .png/.jpg/.jpeg concept image")
    image_parser.add_argument("--name", required=True, help="Asset slug/name, e.g. coin")
    image_parser.add_argument("--out", required=True, help="Output folder, e.g. Assets/QuizRush/Generated/AI3D/coin")
    image_parser.add_argument("--target-polycount", type=int, default=12000, help="Target polygon count")
    image_parser.add_argument("--model-type", choices=["standard", "lowpoly"], default="standard")
    image_parser.add_argument("--no-pbr", action="store_true", help="Disable PBR texture generation")
    image_parser.add_argument("--no-remesh", action="store_true", help="Disable remesh")
    image_parser.add_argument("--poll-interval", type=int, default=DEFAULT_POLL_INTERVAL_SECONDS)
    image_parser.add_argument("--max-wait", type=int, default=1800, help="Max wait seconds for Meshy task")
    image_parser.add_argument("--api-key-file", default=".secrets/meshy_api_key", help="Optional local file containing Meshy API key")
    image_parser.set_defaults(func=run_image_to_3d)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except MeshyError as exc:
        print(f"[meshy:error] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
