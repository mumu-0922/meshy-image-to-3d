#!/usr/bin/env python3
"""Meshy API helper for QuizRush AI 3D assets.

Usage:
  export MESHY_API_KEY="msy_..."
  python3 tools/ai3d/meshy_client.py image-to-3d \
    --image docs/V2/VisualReferences/AI3DConcepts/coin.png \
    --name coin \
    --out Assets/QuizRush/Generated/AI3D/coin \
    --target-polycount 12000 \
    --format glb

  python3 tools/ai3d/meshy_client.py image-to-3d \
    --image docs/V2/VisualReferences/female-runner-pink-ponytail-v2/female_runner_pink_ponytail_01.png \
    --name female_runner_pink_ponytail_01 \
    --out Assets/QuizRush/Generated/AI3D/female_runner_pink_ponytail_01 \
    --target-polycount 30000 \
    --format fbx \
    --topology quad \
    --pose-mode a-pose

  python3 tools/ai3d/meshy_client.py batch-image-to-3d \
    --image-dir docs/V2/VisualReferences/AI3DConcepts \
    --out-root Assets/QuizRush/Generated/AI3D \
    --concurrency 4 \
    --skip-existing
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
from typing import Any, Dict, List, Optional, Sequence, Tuple

MESHY_BASE_URL = "https://api.meshy.ai"
IMAGE_TO_3D_ENDPOINT = f"{MESHY_BASE_URL}/openapi/v1/image-to-3d"
DEFAULT_POLL_INTERVAL_SECONDS = 10
DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_BATCH_CONCURRENCY = 4
DEFAULT_OUT_ROOT = "Assets/QuizRush/Generated/AI3D"
DEFAULT_RATE_LIMIT_RETRIES = 5
DEFAULT_RATE_LIMIT_BACKOFF_SECONDS = 30
SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}
SUPPORTED_MODEL_FORMATS = ("glb", "obj", "fbx", "stl", "usdz", "3mf")
DEFAULT_TARGET_FORMAT = "glb"
RATE_LIMIT_MARKERS = ("RateLimitExceeded", "NoMoreConcurrentTasks", "Too Many Requests")


class MeshyError(RuntimeError):
    pass


class MeshyHttpError(MeshyError):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"Meshy API HTTP {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail

    @property
    def is_rate_limit(self) -> bool:
        return self.status_code == 429 or any(marker in self.detail for marker in RATE_LIMIT_MARKERS)


def require_api_key(api_key_file: Optional[str] = None) -> str:
    api_key = os.environ.get("MESHY_API_KEY", "").strip()

    if not api_key and api_key_file:
        key_path = Path(api_key_file).expanduser()
        if key_path.exists():
            api_key = key_path.read_text(encoding="utf-8").strip()

    if not api_key:
        raise MeshyError("MESHY_API_KEY is not set. Set it in your shell or put it in .secrets/meshy_api_key.")
    return api_key


def json_request(method: str, url: str, api_key: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    body = None
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}

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
        raise MeshyHttpError(exc.code, detail) from exc
    except urllib.error.URLError as exc:
        raise MeshyError(f"Meshy API network error: {exc}") from exc


def request_with_rate_limit_retry(
    operation_name: str,
    func,
    retries: int,
    backoff_seconds: int,
    log_prefix: str,
):
    attempt = 0
    while True:
        try:
            return func()
        except MeshyHttpError as exc:
            if not exc.is_rate_limit or attempt >= retries:
                raise
            delay = backoff_seconds * (2 ** attempt)
            attempt += 1
            print(
                f"{log_prefix} rate limited during {operation_name}; retry={attempt}/{retries} wait={delay}s",
                flush=True,
            )
            time.sleep(delay)


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


def safe_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def create_image_to_3d_task(
    api_key: str,
    image_data_uri: str,
    target_polycount: int,
    enable_pbr: bool,
    should_remesh: bool,
    model_type: str,
    target_format: str,
    topology: str,
    pose_mode: str,
) -> str:
    payload: Dict[str, Any] = {
        "image_url": image_data_uri,
        "ai_model": "latest",
        "model_type": model_type,
        "should_texture": True,
        "enable_pbr": enable_pbr,
        "should_remesh": should_remesh,
        "target_polycount": target_polycount,
        "target_formats": [target_format],
        "multi_view_thumbnails": True,
        "auto_size": True,
        "origin_at": "bottom",
    }
    if should_remesh:
        payload["topology"] = topology
    if pose_mode:
        payload["pose_mode"] = pose_mode

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
    log_prefix: str,
    rate_limit_retries: int,
    rate_limit_backoff_seconds: int,
) -> Dict[str, Any]:
    deadline = time.time() + max_wait_seconds
    last_status = ""

    while True:
        task = request_with_rate_limit_retry(
            "poll",
            lambda: retrieve_image_to_3d_task(api_key, task_id),
            retries=rate_limit_retries,
            backoff_seconds=rate_limit_backoff_seconds,
            log_prefix=log_prefix,
        )
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


def write_asset_readme(
    out_dir: Path,
    asset_name: str,
    source_image: Path,
    task_id: str,
    target_polycount: int,
    target_format: str,
    topology: str,
    pose_mode: str,
) -> None:
    unity_checklist = """- Import GLB in Unity/Tuanjie with glTFast.
- Check scale and pivot.
- Use simple collider/trigger, not high-poly MeshCollider.
- Create runtime prefab only after visual/performance acceptance.
"""
    if target_format == "fbx":
        unity_checklist = """- Import FBX in Unity/Tuanjie.
- For characters, set rig/Avatar to match the existing runner skeleton after retopo/bind/skin transfer.
- Reuse the existing Animator Controller only after Avatar mapping and animation retargeting are verified.
- Check scale, pivot, materials, normals, and texture assignment before wiring gameplay.
"""

    readme = f"""# {asset_name} Meshy AI 3D Asset

Generated by `tools/ai3d/meshy_client.py`.

## Source

- Source image: `source/{source_image.name}`
- Meshy task id: `{task_id}`
- Target polycount: `{target_polycount}`
- Target format: `{target_format}`
- Topology: `{topology}`
- Pose mode: `{pose_mode or 'none'}`

## Output

- Model: `model/{asset_name}.{target_format}`
- Task archive: `source/meshy-task.json`
- Preview images: `preview/`

## Unity checklist

{unity_checklist.rstrip()}
"""
    (out_dir / "README.md").write_text(readme, encoding="utf-8")


def expected_model_path(out_dir: Path, asset_name: str, target_format: str) -> Path:
    return out_dir / "model" / f"{asset_name}.{target_format}"


def normalize_target_format(target_format: str) -> str:
    normalized = target_format.strip().lower()
    if normalized not in SUPPORTED_MODEL_FORMATS:
        raise MeshyError(
            f"Unsupported target format: {target_format}. "
            f"Use one of: {', '.join(SUPPORTED_MODEL_FORMATS)}"
        )
    return normalized


def generate_image_to_3d(
    api_key: str,
    image_path: Path,
    out_dir: Path,
    asset_name: str,
    target_polycount: int,
    enable_pbr: bool,
    should_remesh: bool,
    model_type: str,
    target_format: str,
    topology: str,
    pose_mode: str,
    poll_interval: int,
    max_wait: int,
    log_prefix: str,
    skip_existing: bool,
    rate_limit_retries: int,
    rate_limit_backoff_seconds: int,
) -> Tuple[str, Path, Optional[str]]:
    image_path = image_path.resolve()
    asset_name = asset_name.strip()
    if not asset_name:
        raise MeshyError("asset name must not be empty")
    target_format = normalize_target_format(target_format)

    model_path = expected_model_path(out_dir, asset_name, target_format)
    if skip_existing and model_path.exists() and model_path.stat().st_size > 0:
        print(f"{log_prefix} skip existing {target_format.upper()} -> {model_path}", flush=True)
        return "skipped", model_path, None

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
    task_id = request_with_rate_limit_retry(
        "create",
        lambda: create_image_to_3d_task(
            api_key=api_key,
            image_data_uri=file_to_data_uri(image_path),
            target_polycount=target_polycount,
            enable_pbr=enable_pbr,
            should_remesh=should_remesh,
            model_type=model_type,
            target_format=target_format,
            topology=topology,
            pose_mode=pose_mode,
        ),
        retries=rate_limit_retries,
        backoff_seconds=rate_limit_backoff_seconds,
        log_prefix=log_prefix,
    )
    print(f"{log_prefix} created task {task_id}", flush=True)

    task = poll_task(
        api_key=api_key,
        task_id=task_id,
        interval_seconds=poll_interval,
        max_wait_seconds=max_wait,
        log_prefix=log_prefix,
        rate_limit_retries=rate_limit_retries,
        rate_limit_backoff_seconds=rate_limit_backoff_seconds,
    )

    model_urls = task.get("model_urls") or {}
    model_url = model_urls.get(target_format)
    if not model_url:
        raise MeshyError(f"Succeeded task has no {target_format.upper()} URL: {task}")

    print(f"{log_prefix} downloading {target_format.upper()} -> {model_path}", flush=True)
    download_url(str(model_url), model_path)

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
    write_asset_readme(out_dir, asset_name, image_path, task_id, target_polycount, target_format, topology, pose_mode)

    print(f"{log_prefix} done", flush=True)
    print(f"{log_prefix} model: {model_path}", flush=True)
    return "succeeded", model_path, task_id


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
        target_format=args.format,
        topology=args.topology,
        pose_mode=args.pose_mode,
        poll_interval=args.poll_interval,
        max_wait=args.max_wait,
        log_prefix="[meshy]",
        skip_existing=args.skip_existing,
        rate_limit_retries=args.rate_limit_retries,
        rate_limit_backoff_seconds=args.rate_limit_backoff,
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


def load_batch_manifest(
    path: Path,
    out_root: Path,
    default_target_polycount: int,
    default_model_type: str,
    default_target_format: str,
    default_topology: str,
    default_pose_mode: str,
) -> List[Dict[str, Any]]:
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
                "format": normalize_target_format(str(raw.get("format") or raw.get("target_format") or default_target_format)),
                "topology": str(raw.get("topology", default_topology)),
                "pose_mode": str(raw.get("pose_mode", default_pose_mode)),
            }
        )
    return items


def build_batch_items(args: argparse.Namespace) -> List[Dict[str, Any]]:
    out_root = Path(args.out_root)
    if args.manifest:
        return load_batch_manifest(
            Path(args.manifest),
            out_root,
            args.target_polycount,
            args.model_type,
            args.format,
            args.topology,
            args.pose_mode,
        )

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
                "format": normalize_target_format(args.format),
                "topology": args.topology,
                "pose_mode": args.pose_mode,
            }
        )
    return items


def item_summary(item: Dict[str, Any], status: str, model_path: Optional[str] = None, task_id: Optional[str] = None, error: Optional[str] = None) -> Dict[str, Any]:
    return {
        "name": str(item["name"]),
        "image": str(item["image"]),
        "out": str(item["out"]),
        "format": str(item.get("format", DEFAULT_TARGET_FORMAT)),
        "status": status,
        "model": model_path,
        "task_id": task_id,
        "error": error,
    }


def run_batch_image_to_3d(args: argparse.Namespace) -> int:
    if args.concurrency < 1:
        raise MeshyError("--concurrency must be >= 1")

    items = build_batch_items(args)
    if not items:
        raise MeshyError("No images found for batch generation")

    print(f"[meshy:batch] assets={len(items)} concurrency={args.concurrency} out_root={args.out_root}", flush=True)

    summary: Dict[str, Any] = {
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "concurrency": args.concurrency,
        "out_root": str(args.out_root),
        "items": [],
    }

    if args.dry_run:
        for item in items:
            model = expected_model_path(Path(item["out"]), str(item["name"]), str(item.get("format", args.format)))
            print(f"[meshy:batch] dry-run name={item['name']} image={item['image']} out={item['out']}")
            summary["items"].append(item_summary(item, "planned", str(model)))
        if args.summary:
            safe_write_json(Path(args.summary), summary)
        return 0

    api_key = require_api_key(args.api_key_file)
    failures: List[str] = []
    successes: List[str] = []
    skipped: List[str] = []

    def worker(item: Dict[str, Any]) -> Dict[str, Any]:
        name = str(item["name"])
        status, glb_path, task_id = generate_image_to_3d(
            api_key=api_key,
            image_path=Path(item["image"]),
            out_dir=Path(item["out"]),
            asset_name=name,
            target_polycount=int(item["target_polycount"]),
            enable_pbr=not args.no_pbr,
            should_remesh=not args.no_remesh,
            model_type=str(item["model_type"]),
            target_format=str(item.get("format", args.format)),
            topology=str(item.get("topology", args.topology)),
            pose_mode=str(item.get("pose_mode", args.pose_mode)),
            poll_interval=args.poll_interval,
            max_wait=args.max_wait,
            log_prefix=f"[meshy:{name}]",
            skip_existing=args.skip_existing,
            rate_limit_retries=args.rate_limit_retries,
            rate_limit_backoff_seconds=args.rate_limit_backoff,
        )
        return item_summary(item, status, str(glb_path), task_id)

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        future_to_item = {executor.submit(worker, item): item for item in items}
        for future in concurrent.futures.as_completed(future_to_item):
            item = future_to_item[future]
            name = str(item["name"])
            try:
                result = future.result()
                summary["items"].append(result)
                if result["status"] == "skipped":
                    skipped.append(name)
                    print(f"[meshy:batch] skipped name={name} model={result['model']}", flush=True)
                else:
                    successes.append(name)
                    print(f"[meshy:batch] succeeded name={name} model={result['model']}", flush=True)
            except Exception as exc:  # noqa: BLE001 - collect every asset failure, then return non-zero.
                failures.append(name)
                summary["items"].append(item_summary(item, "failed", error=str(exc)))
                print(f"[meshy:batch:error] failed name={name}: {exc}", file=sys.stderr, flush=True)

    summary["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    summary["counts"] = {"succeeded": len(successes), "skipped": len(skipped), "failed": len(failures)}
    if args.summary:
        safe_write_json(Path(args.summary), summary)

    print(
        f"[meshy:batch] complete succeeded={len(successes)} skipped={len(skipped)} failed={len(failures)}",
        flush=True,
    )
    if failures:
        print(f"[meshy:batch:error] failed assets: {', '.join(failures)}", file=sys.stderr, flush=True)
        return 1
    return 0


def run_make_manifest(args: argparse.Namespace) -> int:
    image_paths = iter_image_dir(Path(args.image_dir), args.recursive)
    if not image_paths:
        raise MeshyError("No images found for manifest generation")

    assets = []
    used_names = set()
    for image_path in image_paths:
        base_name = slugify(image_path.stem)
        name = base_name
        suffix = 2
        while name in used_names:
            name = f"{base_name}_{suffix}"
            suffix += 1
        used_names.add(name)
        assets.append({"image": str(image_path), "name": name})

    manifest = {"assets": assets}
    if args.out:
        safe_write_json(Path(args.out), manifest)
        print(f"[meshy:manifest] wrote {args.out} assets={len(assets)}", flush=True)
    else:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


def run_install_project(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root)
    source_script = Path(__file__).resolve()
    dest_script = project_root / "tools" / "ai3d" / "meshy_client.py"
    dest_script.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_script, dest_script)
    print(f"[meshy:install] copied {source_script} -> {dest_script}", flush=True)

    if args.with_key_template:
        template = source_script.parents[1] / "assets" / ".secrets" / "meshy_api_key.example"
        dest_key = project_root / ".secrets" / "meshy_api_key"
        dest_key.parent.mkdir(parents=True, exist_ok=True)
        if dest_key.exists() and not args.force_key:
            print(f"[meshy:install] key exists, left untouched: {dest_key}", flush=True)
        else:
            shutil.copy2(template, dest_key)
            print(f"[meshy:install] copied key template -> {dest_key}", flush=True)
    return 0


def add_common_generation_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--target-polycount", type=int, default=12000, help="Target polygon count")
    parser.add_argument("--model-type", choices=["standard", "lowpoly"], default="standard")
    parser.add_argument("--format", "--target-format", choices=SUPPORTED_MODEL_FORMATS, default=DEFAULT_TARGET_FORMAT, help="Downloaded Meshy model format")
    parser.add_argument("--topology", choices=["triangle", "quad"], default="triangle", help="Remesh topology when remesh is enabled")
    parser.add_argument("--pose-mode", choices=["", "a-pose", "t-pose"], default="", help="Character pose mode; use a-pose/t-pose for rigging pipelines")
    parser.add_argument("--no-pbr", action="store_true", help="Disable PBR texture generation")
    parser.add_argument("--no-remesh", action="store_true", help="Disable remesh")
    parser.add_argument("--poll-interval", type=int, default=DEFAULT_POLL_INTERVAL_SECONDS)
    parser.add_argument("--max-wait", type=int, default=1800, help="Max wait seconds per Meshy task")
    parser.add_argument("--api-key-file", default=".secrets/meshy_api_key", help="Optional local file containing Meshy API key")
    parser.add_argument("--skip-existing", action="store_true", help="Skip when output model/<name>.<format> already exists")
    parser.add_argument("--rate-limit-retries", type=int, default=DEFAULT_RATE_LIMIT_RETRIES, help="Retries for Meshy 429 rate/queue limits")
    parser.add_argument("--rate-limit-backoff", type=int, default=DEFAULT_RATE_LIMIT_BACKOFF_SECONDS, help="Base seconds for exponential 429 backoff")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="QuizRush Meshy AI 3D asset client")
    subparsers = parser.add_subparsers(dest="command", required=True)

    image_parser = subparsers.add_parser("image-to-3d", help="Create one Meshy image-to-3d task and download a model")
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
    batch_parser.add_argument("--summary", default="batch-summary.json", help="Write batch summary JSON; use empty string to disable")
    add_common_generation_args(batch_parser)
    batch_parser.set_defaults(func=run_batch_image_to_3d)

    manifest_parser = subparsers.add_parser("make-manifest", help="Create a batch manifest from an image directory")
    manifest_parser.add_argument("--image-dir", required=True, help="Directory containing .png/.jpg/.jpeg concept images")
    manifest_parser.add_argument("--out", help="Manifest JSON output path; prints to stdout if omitted")
    manifest_parser.add_argument("--recursive", action="store_true", help="Recursively scan --image-dir")
    manifest_parser.set_defaults(func=run_make_manifest)

    install_parser = subparsers.add_parser("install-project", help="Copy this bundled client into a Unity project")
    install_parser.add_argument("--project-root", default=".", help="Unity project root")
    install_parser.add_argument("--with-key-template", action="store_true", help="Also copy meshy_api_key.example to .secrets/meshy_api_key")
    install_parser.add_argument("--force-key", action="store_true", help="Overwrite existing .secrets/meshy_api_key when used with --with-key-template")
    install_parser.set_defaults(func=run_install_project)

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
