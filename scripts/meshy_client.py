#!/usr/bin/env python3
"""Meshy API helper for QuizRush AI 3D assets.

Usage:
  export MESHY_API_KEY="msy_..."
  python3 tools/ai3d/meshy_client.py image-to-3d \
    --image docs/V2/VisualReferences/AI3DConcepts/coin.png \
    --name coin \
    --out Assets/QuizRush/Generated/AI3D/coin \
    --target-polycount 12000

  python3 tools/ai3d/meshy_client.py batch-image-to-3d \
    --image-dir docs/V2/VisualReferences/AI3DConcepts \
    --out-root Assets/QuizRush/Generated/AI3D \
    --concurrency 4
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import json
import mimetypes
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

MESHY_BASE_URL = "https://api.meshy.ai"
IMAGE_TO_3D_ENDPOINT = f"{MESHY_BASE_URL}/openapi/v1/image-to-3d"
DEFAULT_POLL_INTERVAL_SECONDS = 10
DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_BATCH_CONCURRENCY = 4
DEFAULT_OUT_ROOT = "Assets/QuizRush/Generated/AI3D"
SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}


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


def poll_task(
    api_key: str,
    task_id: str,
    interval_seconds: int,
    max_wait_seconds: int,
    log_prefix: str = "[meshy]",
) -> Dict[str, Any]:
    deadline = time.time() + max_wait_seconds
    last_status = ""

    while True:
        task = retrieve_image_to_3d_task(api_key, task_id)
        status = str(task.get("status", "UNKNOWN"))
        progress = task.get("progress", 0)

        if status != last_status or status in {"PENDING", "IN_PROGRESS"}:
            print(f"{log_prefix} task={task_id} status={status} progress={progress}%", flush=True)
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


def generate_image_to_3d(
    api_key: str,
    image_path: Path,
    out_dir: Path,
    asset_name: str,
    target_polycount: int,
    enable_pbr: bool,
    should_remesh: bool,
    model_type: str,
    poll_interval: int,
    max_wait: int,
    log_prefix: str = "[meshy]",
) -> Path:
    image_path = image_path.resolve()
    asset_name = asset_name.strip()
    if not asset_name:
        raise MeshyError("asset name must not be empty")

    source_dir = out_dir / "source"
    model_dir = out_dir / "model"
    preview_dir = out_dir / "preview"
    source_dir.mkdir(parents=True, exist_ok=True)
    model_dir.mkdir(parents=True, exist_ok=True)
    preview_dir.mkdir(parents=True, exist_ok=True)

    source_copy = source_dir / image_path.name
    if image_path != source_copy.resolve():
        shutil.copy2(image_path, source_copy)

    print(f"{log_prefix} creating image-to-3d task for {asset_name}", flush=True)
    task_id = create_image_to_3d_task(
        api_key=api_key,
        image_data_uri=file_to_data_uri(image_path),
        target_polycount=target_polycount,
        enable_pbr=enable_pbr,
        should_remesh=should_remesh,
        model_type=model_type,
    )
    print(f"{log_prefix} created task {task_id}", flush=True)

    task = poll_task(
        api_key=api_key,
        task_id=task_id,
        interval_seconds=poll_interval,
        max_wait_seconds=max_wait,
        log_prefix=log_prefix,
    )

    model_urls = task.get("model_urls") or {}
    glb_url = model_urls.get("glb")
    if not glb_url:
        raise MeshyError(f"Succeeded task has no GLB URL: {task}")

    glb_path = model_dir / f"{asset_name}.glb"
    print(f"{log_prefix} downloading GLB -> {glb_path}", flush=True)
    download_url(str(glb_url), glb_path)

    thumbnail_url = task.get("thumbnail_url")
    if thumbnail_url:
        print(f"{log_prefix} downloading preview thumbnail", flush=True)
        download_url(str(thumbnail_url), preview_dir / "preview.png")

    thumbnail_urls = task.get("thumbnail_urls") or {}
    if isinstance(thumbnail_urls, dict):
        for view_name, view_url in thumbnail_urls.items():
            if view_url:
                print(f"{log_prefix} downloading {view_name} thumbnail", flush=True)
                download_url(str(view_url), preview_dir / f"{view_name}.png")

    safe_write_json(source_dir / "meshy-task.json", redact_task_for_archive(task))
    write_asset_readme(out_dir, asset_name, image_path, task_id, target_polycount)

    print(f"{log_prefix} done", flush=True)
    print(f"{log_prefix} model: {glb_path}", flush=True)
    return glb_path


def run_image_to_3d(args: argparse.Namespace) -> int:
    api_key = require_api_key(args.api_key_file)
    generate_image_to_3d(
        api_key=api_key,
        image_path=Path(args.image),
        out_dir=Path(args.out),
        asset_name=args.name,
        target_polycount=args.target_polycount,
        enable_pbr=not args.no_pbr,
        should_remesh=not args.no_remesh,
        model_type=args.model_type,
        poll_interval=args.poll_interval,
        max_wait=args.max_wait,
    )
    return 0


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", value.strip().lower())
    slug = re.sub(r"_+", "_", slug).strip("_-")
    return slug or "asset"


def iter_image_dir(image_dir: Path, recursive: bool) -> List[Path]:
    if not image_dir.exists():
        raise MeshyError(f"Image directory does not exist: {image_dir}")
    if not image_dir.is_dir():
        raise MeshyError(f"Image directory is not a directory: {image_dir}")

    iterator = image_dir.rglob("*") if recursive else image_dir.iterdir()
    images = [path for path in iterator if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES]
    return sorted(images, key=lambda path: str(path).lower())


def load_batch_manifest(path: Path, out_root: Path, default_target_polycount: int, default_model_type: str) -> List[Dict[str, Any]]:
    if not path.exists():
        raise MeshyError(f"Manifest does not exist: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        raw_items = data.get("assets") or data.get("items")
    else:
        raw_items = data

    if not isinstance(raw_items, list):
        raise MeshyError("Batch manifest must be a JSON list or an object with assets/items list")

    items: List[Dict[str, Any]] = []
    for index, raw in enumerate(raw_items, start=1):
        if not isinstance(raw, dict):
            raise MeshyError(f"Manifest item #{index} must be an object")
        image = raw.get("image") or raw.get("image_path")
        if not image:
            raise MeshyError(f"Manifest item #{index} missing image")
        name = str(raw.get("name") or slugify(Path(str(image)).stem))
        out = Path(str(raw.get("out") or out_root / name))
        items.append(
            {
                "image": Path(str(image)),
                "name": name,
                "out": out,
                "target_polycount": int(raw.get("target_polycount", default_target_polycount)),
                "model_type": str(raw.get("model_type", default_model_type)),
            }
        )
    return items


def build_batch_items(args: argparse.Namespace) -> List[Dict[str, Any]]:
    out_root = Path(args.out_root)
    if args.manifest:
        return load_batch_manifest(Path(args.manifest), out_root, args.target_polycount, args.model_type)

    image_paths = iter_image_dir(Path(args.image_dir), args.recursive)
    items: List[Dict[str, Any]] = []
    used_names = set()
    for image_path in image_paths:
        base_name = slugify(image_path.stem)
        name = base_name
        suffix = 2
        while name in used_names:
            name = f"{base_name}_{suffix}"
            suffix += 1
        used_names.add(name)
        items.append(
            {
                "image": image_path,
                "name": name,
                "out": out_root / name,
                "target_polycount": args.target_polycount,
                "model_type": args.model_type,
            }
        )
    return items


def run_batch_image_to_3d(args: argparse.Namespace) -> int:
    if args.concurrency < 1:
        raise MeshyError("--concurrency must be >= 1")

    items = build_batch_items(args)
    if not items:
        raise MeshyError("No images found for batch generation")

    print(
        f"[meshy:batch] assets={len(items)} concurrency={args.concurrency} out_root={args.out_root}",
        flush=True,
    )

    if args.dry_run:
        for item in items:
            print(f"[meshy:batch] dry-run name={item['name']} image={item['image']} out={item['out']}")
        return 0

    api_key = require_api_key(args.api_key_file)
    failures: List[str] = []
    successes: List[str] = []

    def worker(item: Dict[str, Any]) -> str:
        name = str(item["name"])
        glb_path = generate_image_to_3d(
            api_key=api_key,
            image_path=Path(item["image"]),
            out_dir=Path(item["out"]),
            asset_name=name,
            target_polycount=int(item["target_polycount"]),
            enable_pbr=not args.no_pbr,
            should_remesh=not args.no_remesh,
            model_type=str(item["model_type"]),
            poll_interval=args.poll_interval,
            max_wait=args.max_wait,
            log_prefix=f"[meshy:{name}]",
        )
        return str(glb_path)

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        future_to_name = {executor.submit(worker, item): str(item["name"]) for item in items}
        for future in concurrent.futures.as_completed(future_to_name):
            name = future_to_name[future]
            try:
                glb_path = future.result()
                successes.append(name)
                print(f"[meshy:batch] succeeded name={name} model={glb_path}", flush=True)
            except Exception as exc:  # noqa: BLE001 - print every asset failure, then return non-zero.
                failures.append(name)
                print(f"[meshy:batch:error] failed name={name}: {exc}", file=sys.stderr, flush=True)

    print(f"[meshy:batch] complete succeeded={len(successes)} failed={len(failures)}", flush=True)
    if failures:
        print(f"[meshy:batch:error] failed assets: {', '.join(failures)}", file=sys.stderr, flush=True)
        return 1
    return 0


def add_common_generation_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--target-polycount", type=int, default=12000, help="Target polygon count")
    parser.add_argument("--model-type", choices=["standard", "lowpoly"], default="standard")
    parser.add_argument("--no-pbr", action="store_true", help="Disable PBR texture generation")
    parser.add_argument("--no-remesh", action="store_true", help="Disable remesh")
    parser.add_argument("--poll-interval", type=int, default=DEFAULT_POLL_INTERVAL_SECONDS)
    parser.add_argument("--max-wait", type=int, default=1800, help="Max wait seconds per Meshy task")
    parser.add_argument("--api-key-file", default=".secrets/meshy_api_key", help="Optional local file containing Meshy API key")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="QuizRush Meshy AI 3D asset client")
    subparsers = parser.add_subparsers(dest="command", required=True)

    image_parser = subparsers.add_parser("image-to-3d", help="Create one Meshy image-to-3d task and download GLB")
    image_parser.add_argument("--image", required=True, help="Local .png/.jpg/.jpeg concept image")
    image_parser.add_argument("--name", required=True, help="Asset slug/name, e.g. coin")
    image_parser.add_argument("--out", required=True, help="Output folder, e.g. Assets/QuizRush/Generated/AI3D/coin")
    add_common_generation_args(image_parser)
    image_parser.set_defaults(func=run_image_to_3d)

    batch_parser = subparsers.add_parser("batch-image-to-3d", help="Create many Meshy image-to-3d tasks in parallel")
    source_group = batch_parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--image-dir", help="Directory containing .png/.jpg/.jpeg concept images")
    source_group.add_argument("--manifest", help="JSON list/object with image/name/out items")
    batch_parser.add_argument("--out-root", default=DEFAULT_OUT_ROOT, help="Output root for auto-generated asset folders")
    batch_parser.add_argument("--recursive", action="store_true", help="Recursively scan --image-dir")
    batch_parser.add_argument("--concurrency", type=int, default=DEFAULT_BATCH_CONCURRENCY, help="Parallel Meshy tasks to run")
    batch_parser.add_argument("--dry-run", action="store_true", help="Print planned batch items without calling Meshy")
    add_common_generation_args(batch_parser)
    batch_parser.set_defaults(func=run_batch_image_to_3d)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except MeshyError as exc:
        print(f"[meshy:error] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
