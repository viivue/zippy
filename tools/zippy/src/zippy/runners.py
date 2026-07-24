"""Job execution: wraps the vidopt/imgopt/fontslice packages with progress reporting.

Reuses the tools' own pure functions (resolve_ffmpeg, probe_video,
build_ffmpeg_command, optimize_file, gather_inputs, process_font,
discover_fonts, parse_weight_entry, validate_subsets) rather than
re-implementing their logic. The one exception is real (non-dry-run) video
encodes: vidopt.optimize_file() runs ffmpeg via subprocess.run() and doesn't
expose progress, so this module builds the same ffmpeg command and streams
its `-progress pipe:1` output instead.
"""

from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path
from typing import Any

from .jobs import Job


def _file_result_to_dict(result: Any) -> dict[str, Any]:
    input_size = result.input_size
    output_size = result.output_size
    saved_pct = None
    if result.status in ("OK", "LARGER") and input_size:
        saved_pct = round((input_size - output_size) * 100 / input_size, 1)
    return {
        "file": result.source.name,
        "input_size": input_size,
        "output_size": output_size
        if result.status not in ("FAILED", "DRY-RUN")
        else None,
        "saved_pct": saved_pct,
        "resolution": getattr(result, "resolution", None),
        "status": result.status,
        "error": result.error,
    }


# ── vidopt ────────────────────────────────────────────────────────────────────


def _parse_out_time(value: str) -> float:
    try:
        h, m, s = value.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)
    except ValueError:
        return 0.0


def _run_ffmpeg_with_progress(
    cmd: list[str], duration: float, on_progress
) -> tuple[int, str]:
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1
    )
    stderr_lines: list[str] = []

    def _drain_stderr() -> None:
        for line in proc.stderr:
            stderr_lines.append(line)

    drainer = threading.Thread(target=_drain_stderr, daemon=True)
    drainer.start()

    for line in proc.stdout:
        line = line.strip()
        if line.startswith("out_time="):
            seconds = _parse_out_time(line.split("=", 1)[1])
            if duration > 0:
                on_progress(min(99.0, seconds / duration * 100))
        elif line == "progress=end":
            on_progress(100.0)

    proc.wait()
    drainer.join(timeout=2)
    return proc.returncode, "".join(stderr_lines)


def _encode_with_progress(
    job: Job,
    idx: int,
    total: int,
    ffmpeg: str,
    ffprobe: str,
    source: Path,
    output_dir: Path,
    crf: int,
    preset: str,
    use_h265: bool,
    max_width: int | None,
    overwrite: bool,
) -> Any:
    from vidopt.cli import (
        OUTPUT_EXTENSION,
        FileResult,
        build_ffmpeg_command,
        probe_video,
    )

    input_size = source.stat().st_size
    try:
        info = probe_video(ffprobe, source)
    except Exception as exc:
        return FileResult(
            source=source,
            output=None,
            input_size=input_size,
            output_size=0,
            resolution="?",
            status="FAILED",
            error=f"probe: {exc}",
        )

    resolution = f"{info.width}x{info.height}"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / (source.stem + OUTPUT_EXTENSION)

    if output_path.exists() and not overwrite:
        return FileResult(
            source=source,
            output=output_path,
            input_size=input_size,
            output_size=output_path.stat().st_size,
            resolution=resolution,
            status="SKIPPED",
        )

    cmd = build_ffmpeg_command(
        ffmpeg, source, output_path, info, crf, preset, use_h265, max_width
    )
    progress_cmd = cmd[:-1] + ["-progress", "pipe:1", "-nostats"] + cmd[-1:]

    def _on_progress(pct: float) -> None:
        job.set_progress((idx + pct / 100) / total * 100, current_file=source.name)

    returncode, stderr_text = _run_ffmpeg_with_progress(
        progress_cmd, info.duration, _on_progress
    )

    if returncode != 0:
        excerpt = stderr_text[-600:].strip()
        return FileResult(
            source=source,
            output=None,
            input_size=input_size,
            output_size=0,
            resolution=resolution,
            status="FAILED",
            error=excerpt or "non-zero exit from ffmpeg",
        )

    output_size = output_path.stat().st_size
    is_larger = output_size > input_size
    return FileResult(
        source=source,
        output=output_path,
        input_size=input_size,
        output_size=output_size,
        resolution=resolution,
        status="LARGER" if is_larger else "OK",
    )


def run_vidopt_job(job: Job, params: dict[str, Any]) -> None:
    from vidopt.cli import (
        DEFAULT_QUALITY,
        DEFAULT_SPEED,
        OUTPUT_SUBFOLDER,
        QUALITY_CRF_H264,
        QUALITY_CRF_H265,
        SPEED_PRESET,
        FileResult,
        gather_inputs,
        optimize_file,
        resolve_ffmpeg,
    )

    quality = params.get("quality") or DEFAULT_QUALITY
    speed = params.get("speed") or DEFAULT_SPEED
    h265 = bool(params.get("h265"))
    max_width = params.get("max_width")
    recursive = bool(params.get("recursive"))
    overwrite = bool(params.get("overwrite"))
    dry_run = bool(params.get("dry_run"))

    crf = (QUALITY_CRF_H265 if h265 else QUALITY_CRF_H264)[quality]
    preset = SPEED_PRESET[speed]

    ffmpeg, ffprobe = resolve_ffmpeg()

    input_path = Path(params["input"])
    files = gather_inputs(input_path, recursive=recursive)
    if not files:
        job.set_summary(
            {
                "message": "No supported video files found.",
                "net_saved": 0,
                "failures": 0,
                "total": 0,
            }
        )
        return

    if params.get("output"):
        output_root = Path(params["output"])
    else:
        base = input_path if input_path.is_dir() else input_path.parent
        output_root = base / OUTPUT_SUBFOLDER

    total = len(files)
    net_saved = 0
    failures = 0

    for idx, source_file in enumerate(files):
        if input_path.is_dir() and recursive:
            rel = source_file.parent.relative_to(input_path)
            output_dir = output_root / rel
        else:
            output_dir = output_root

        job.set_progress(idx / total * 100, current_file=source_file.name)

        try:
            if dry_run:
                result = optimize_file(
                    ffmpeg=ffmpeg,
                    ffprobe=ffprobe,
                    source=source_file,
                    output_dir=output_dir,
                    crf=crf,
                    preset=preset,
                    use_h265=h265,
                    max_width=max_width,
                    overwrite=overwrite,
                    dry_run=True,
                )
            else:
                result = _encode_with_progress(
                    job,
                    idx,
                    total,
                    ffmpeg,
                    ffprobe,
                    source_file,
                    output_dir,
                    crf,
                    preset,
                    h265,
                    max_width,
                    overwrite,
                )
        except Exception as exc:
            size = source_file.stat().st_size if source_file.exists() else 0
            result = FileResult(
                source=source_file,
                output=None,
                input_size=size,
                output_size=0,
                resolution="?",
                status="FAILED",
                error=str(exc),
            )

        if result.status == "FAILED":
            failures += 1
        elif result.status in ("OK", "LARGER"):
            net_saved += result.input_size - result.output_size

        job.add_result(_file_result_to_dict(result))

    job.set_progress(100.0, current_file=None)
    job.set_summary({"net_saved": net_saved, "failures": failures, "total": total})
    if failures:
        job.status = "failed"
        job.error = f"{failures} of {total} file(s) failed"


# ── imgopt ────────────────────────────────────────────────────────────────────


def run_imgopt_job(job: Job, params: dict[str, Any]) -> None:
    from imgopt.cli import (
        DEFAULT_QUALITY,
        OUTPUT_SUBFOLDER,
        FileResult,
        gather_inputs,
        optimize_file,
    )

    quality = params.get("quality") or DEFAULT_QUALITY
    fmt = params.get("format") or "original"
    to_webp = fmt == "webp"
    to_jpg = fmt == "jpg"
    max_width = params.get("max_width")
    max_height = params.get("max_height")
    keep_exif = bool(params.get("keep_exif"))
    recursive = bool(params.get("recursive"))
    overwrite = bool(params.get("overwrite"))
    dry_run = bool(params.get("dry_run"))

    input_path = Path(params["input"])
    files = gather_inputs(input_path, recursive=recursive)
    if not files:
        job.set_summary(
            {
                "message": "No supported image files found.",
                "net_saved": 0,
                "failures": 0,
                "total": 0,
            }
        )
        return

    if params.get("output"):
        output_root = Path(params["output"])
    else:
        base = input_path if input_path.is_dir() else input_path.parent
        output_root = base / OUTPUT_SUBFOLDER

    total = len(files)
    net_saved = 0
    failures = 0

    for idx, source_file in enumerate(files):
        if input_path.is_dir() and recursive:
            rel = source_file.parent.relative_to(input_path)
            output_dir = output_root / rel
        else:
            output_dir = output_root

        job.set_progress(idx / total * 100, current_file=source_file.name)

        try:
            result = optimize_file(
                source=source_file,
                output_dir=output_dir,
                quality=quality,
                max_width=max_width,
                max_height=max_height,
                to_webp=to_webp,
                to_jpg=to_jpg,
                strip_exif=not keep_exif,
                overwrite=overwrite,
                dry_run=dry_run,
            )
        except Exception as exc:
            size = source_file.stat().st_size if source_file.exists() else 0
            result = FileResult(
                source=source_file,
                output=None,
                input_size=size,
                output_size=0,
                status="FAILED",
                error=str(exc),
            )

        if result.status == "FAILED":
            failures += 1
        elif result.status in ("OK", "LARGER"):
            net_saved += result.input_size - result.output_size

        job.add_result(_file_result_to_dict(result))

    job.set_progress(100.0, current_file=None)
    job.set_summary({"net_saved": net_saved, "failures": failures, "total": total})
    if failures:
        job.status = "failed"
        job.error = f"{failures} of {total} file(s) failed"


# ── fontslice ─────────────────────────────────────────────────────────────────


def run_fontslice_job(job: Job, params: dict[str, Any]) -> None:
    from fontslice.cli import parse_weight_entry, validate_subsets
    from fontslice.subset_font import process_font

    fonts_dir = params["fonts_dir"]
    text_file = params.get("text_file") or None
    subsets_list = params.get("subsets") or []

    if text_file:
        if not os.path.isfile(text_file):
            raise FileNotFoundError(f"text file not found: {text_file}")
        subsets_csv = None
    else:
        subsets_csv = validate_subsets(
            ",".join(subsets_list) if subsets_list else "latin"
        )

    fonts = params.get("fonts") or []
    if not fonts:
        job.set_summary(
            {"message": "No fonts selected.", "net_saved": 0, "failures": 0, "total": 0}
        )
        return

    # Resolve per-font weight jobs up front so the total step count is known.
    plan: list[tuple[dict, str, str]] = []
    for font in fonts:
        is_web_src = font["font_path"].lower().endswith((".woff", ".woff2"))
        base_stem = font["basename"] + (".opt" if is_web_src else "")
        override = (font.get("weight_override") or "").strip()

        spec = None
        if override:
            try:
                spec = parse_weight_entry(override)
            except ValueError as exc:
                raise ValueError(f"{font['basename']}: {exc}") from exc

        if spec is None:
            wmin, wmax = font["weight_min"], font["weight_max"]
            w = wmin if wmin == wmax else f"{wmin}:{wmax}"
            plan.append((font, w, base_stem))
        elif spec["kind"] == "range":
            lo, hi = spec["values"]
            w = f"{lo}:{hi}" if lo != hi else str(lo)
            plan.append((font, w, base_stem))
        else:
            for pin in spec["values"]:
                plan.append((font, str(pin), f"{base_stem}-{pin}"))

    total = len(plan)
    net_saved = 0
    failures = 0
    built: list[dict] = []

    for idx, (font, weight_arg, out_stem) in enumerate(plan):
        job.set_progress(idx / total * 100, current_file=out_stem)
        orig_size = os.path.getsize(font["font_path"])
        try:
            sizes = process_font(
                src=font["font_path"],
                output_base=os.path.join(fonts_dir, out_stem),
                weight=weight_arg,
                opsz=font.get("opsz") or None,
                subsets=subsets_csv or "latin",
                text_file=text_file,
            )
            woff2_size = sizes.get("woff2", 0)
            saved_pct = (
                round((1 - woff2_size / orig_size) * 100, 1) if orig_size else 0.0
            )
            job.add_result(
                {
                    "file": out_stem + ".woff2",
                    "input_size": orig_size,
                    "output_size": woff2_size,
                    "saved_pct": saved_pct,
                    "status": "OK",
                    "error": "",
                }
            )
            net_saved += orig_size - woff2_size
            built.append(
                {
                    **font,
                    "out_stem": out_stem,
                    "weight_arg": weight_arg,
                    "woff2_size": woff2_size,
                }
            )
        except (FileNotFoundError, ValueError, RuntimeError) as exc:
            failures += 1
            job.add_result(
                {
                    "file": out_stem + ".woff2",
                    "input_size": orig_size,
                    "output_size": None,
                    "saved_pct": None,
                    "status": "FAILED",
                    "error": str(exc),
                }
            )

    job.set_progress(100.0, current_file=None)

    css_blocks = []
    for b in built:
        w = b["weight_arg"]
        wrange = w.replace(":", " ") if ":" in w else w
        woff2_file = b["out_stem"] + ".woff2"
        css_blocks.append(
            "@font-face {\n"
            f"  font-family: '{b['family_name']}';\n"
            f"  src: url('assets/fonts/{woff2_file}') format('woff2');\n"
            f"  font-weight: {wrange};\n"
            "  font-style: normal;\n"
            "  font-display: swap;\n"
            "}"
        )

    job.set_summary(
        {
            "net_saved": net_saved,
            "failures": failures,
            "total": total,
            "font_face_css": "\n\n".join(css_blocks),
        }
    )
    if failures:
        job.status = "failed"
        job.error = f"{failures} of {total} build(s) failed"
