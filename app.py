"""
video_to_dotlottie.py
─────────────────────
Convert a video file to a dotLottie (.lottie) or plain Lottie (.json)
animation, with optional background removal per frame.

Key improvements over v1
────────────────────────
• FPS-based frame sampling  - choose *output* fps (e.g. 12) independently of
  the source video fps.  The sampler picks the nearest source frame for each
  target timestamp, so you always get the right number of frames per second.
• Robust Lottie JSON  - animation-level `w`, `h`, `fr`, `ip`, `op` are all
  set correctly; every image asset carries its real pixel dimensions; layer
  `ind`, `st`, `ip`, `op` are set explicitly.
• Clean asset ids  - "img_000", "img_001", … (zero-padded) for readability.
• JSON export option  - pass --format json to write a plain .json Lottie file
  instead of the zipped .lottie container.
• Graceful cleanup  - temp folder is always removed unless --keep-temp is set,
  even when an exception is raised mid-run.
• Verbose progress bar with ETA (no external deps).
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import shutil
import time
import zipfile
from typing import NamedTuple

import cv2
from PIL import Image as PILImage
from rembg import remove as rembg_remove

ANIM_ID = "animation"


# ═══════════════════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════════════════

class FrameInfo(NamedTuple):
    path    : str
    width   : int
    height  : int


class VideoInfo(NamedTuple):
    width         : int
    height        : int
    fps           : float
    frame_count   : int
    duration_s    : float
    file_size_mb  : float
    codec         : str          # fourcc string, e.g. "avc1"
    bitrate_kbps  : float        # estimated from file size & duration
    aspect_ratio  : str          # e.g. "16:9"
    quality_label : str          # e.g. "4K", "1080p", "720p", …
    suggested_scale: float       # recommended output scale for web use


# ── quality label thresholds (height-based) ───────────────────────────────────
_QUALITY_TIERS: list[tuple[int, str]] = [
    (2160, "4K / UHD"),
    (1440, "2K / QHD"),
    (1080, "1080p Full HD"),
    (720,  "720p HD"),
    (480,  "480p SD"),
    (360,  "360p"),
    (0,    "Low res"),
]

# Suggested output scale per quality tier (keeps web output manageable)
_SUGGESTED_SCALE: list[tuple[int, float]] = [
    (2160, 0.25),
    (1440, 0.33),
    (1080, 0.5),
    (720,  0.5),
    (480,  0.75),
    (0,    1.0),
]


def _quality_label(height: int) -> str:
    for threshold, label in _QUALITY_TIERS:
        if height >= threshold:
            return label
    return "Low res"


def _suggested_scale(height: int) -> float:
    for threshold, scale in _SUGGESTED_SCALE:
        if height >= threshold:
            return scale
    return 1.0


def _aspect_ratio(w: int, h: int) -> str:
    """Return a simplified aspect ratio string, e.g. '16:9'."""
    def gcd(a: int, b: int) -> int:
        return a if b == 0 else gcd(b, a % b)
    d = gcd(w, h)
    return f"{w // d}:{h // d}"


def _fourcc_to_str(fourcc_int: float) -> str:
    """Convert OpenCV's float fourcc value to a 4-char string."""
    try:
        code = int(fourcc_int)
        return "".join(chr((code >> (8 * i)) & 0xFF) for i in range(4)).strip("\x00")
    except Exception:
        return "unknown"


def inspect_video(video_path: str) -> VideoInfo:
    """
    Open *video_path* with OpenCV and return a VideoInfo with all key
    properties.  Prints a formatted summary table to stdout.

    Raises IOError if the file cannot be opened.
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video not found: '{video_path}'")

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise IOError(f"Cannot open video: '{video_path}'")

    w           = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h           = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps         = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fourcc_int  = cap.get(cv2.CAP_PROP_FOURCC)
    cap.release()

    duration_s    = frame_count / fps if fps else 0.0
    file_size_mb  = os.path.getsize(video_path) / (1024 * 1024)
    bitrate_kbps  = (file_size_mb * 8 * 1024) / duration_s if duration_s else 0.0
    codec         = _fourcc_to_str(fourcc_int)
    aspect        = _aspect_ratio(w, h)
    qlabel        = _quality_label(h)
    sscale        = _suggested_scale(h)

    info = VideoInfo(
        width          = w,
        height         = h,
        fps            = fps,
        frame_count    = frame_count,
        duration_s     = duration_s,
        file_size_mb   = file_size_mb,
        codec          = codec,
        bitrate_kbps   = bitrate_kbps,
        aspect_ratio   = aspect,
        quality_label  = qlabel,
        suggested_scale= sscale,
    )

    _print_video_info(info, video_path)
    return info


def _print_video_info(info: VideoInfo, path: str) -> None:
    """Pretty-print a VideoInfo summary."""
    mins, secs = divmod(info.duration_s, 60)
    dur_str    = f"{int(mins)}m {secs:.1f}s" if mins else f"{secs:.1f}s"

    rows = [
        ("File",          os.path.basename(path)),
        ("Size",          f"{info.file_size_mb:.1f} MB"),
        ("Resolution",    f"{info.width}×{info.height}  ({info.quality_label})"),
        ("Aspect ratio",  info.aspect_ratio),
        ("Frame rate",    f"{info.fps:.3f} fps"),
        ("Duration",      f"{dur_str}  ({info.frame_count} frames)"),
        ("Codec",         info.codec if info.codec else "unknown"),
        ("Bitrate",       f"~{info.bitrate_kbps:.0f} kbps"),
        ("Suggested scale", f"{info.suggested_scale}  →  "
                            f"{int(info.width * info.suggested_scale)}×"
                            f"{int(info.height * info.suggested_scale)}"),
    ]

    col = max(len(k) for k, _ in rows)
    banner("Video info")
    for key, val in rows:
        print(f"  {key:<{col}}  {val}")

    # Warnings
    if info.file_size_mb > 100:
        print(f"\n  ⚠  Large file ({info.file_size_mb:.0f} MB) - "
              "consider a lower scale or fps to keep output size manageable.")
    if info.duration_s < 1.0:
        print(f"\n  ⚠  Very short clip ({info.duration_s:.2f}s) - "
              "output may have very few frames.")


def _progress(current: int, total: int, prefix: str = "", width: int = 40) -> None:
    """Print a simple ASCII progress bar to stdout."""
    filled = int(width * current / total) if total else 0
    bar    = "█" * filled + "░" * (width - filled)
    pct    = 100 * current / total if total else 0
    print(f"\r      {prefix} [{bar}] {pct:5.1f}%  ({current}/{total})", end="", flush=True)


def _source_frame_indices(source_fps: float, source_count: int,
                           target_fps: float) -> list[int]:
    """
    Return the list of source-frame indices to sample so that the output
    runs at *target_fps*.  Each index is the nearest frame to the ideal
    timestamp.

    Example: source 30 fps, 90 frames → target 12 fps → 36 output frames.
    """
    if target_fps <= 0:
        raise ValueError("target_fps must be > 0")

    duration_s      = source_count / source_fps          # total video duration
    output_count    = max(1, int(math.floor(duration_s * target_fps)))
    step_s          = 1.0 / target_fps                   # seconds per output frame

    indices: list[int] = []
    for k in range(output_count):
        ideal_s   = k * step_s
        src_idx   = int(round(ideal_s * source_fps))
        src_idx   = min(src_idx, source_count - 1)       # clamp
        indices.append(src_idx)

    return indices


# ═══════════════════════════════════════════════════════════════════════════════
# Step 1 – frame extraction
# ═══════════════════════════════════════════════════════════════════════════════

def _save_frame(raw_bgr, scale: float, out_w: int, out_h: int,
                proc_path: str, remove_bg: bool) -> tuple[int, int]:
    """Resize, optionally remove bg, save as RGBA PNG. Returns (width, height)."""
    if scale != 1.0:
        raw_bgr = cv2.resize(raw_bgr, (out_w, out_h), interpolation=cv2.INTER_AREA)
    rgb = cv2.cvtColor(raw_bgr, cv2.COLOR_BGR2RGB)
    img = PILImage.fromarray(rgb)
    processed = rembg_remove(img) if remove_bg else img.convert("RGBA")
    processed.save(proc_path, "PNG")
    return processed.size


def extract_frames(
    video_path  : str,
    temp_folder : str,
    target_fps  : float = 12.0,
    scale       : float = 1.0,
    remove_bg   : bool  = True,
) -> tuple[list[FrameInfo], float]:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise IOError(f"Cannot open video: '{video_path}'")

    source_fps   = cap.get(cv2.CAP_PROP_FPS) or 30.0
    source_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    orig_w       = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    orig_h       = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    out_w        = max(1, int(orig_w * scale))
    out_h        = max(1, int(orig_h * scale))

    if target_fps > source_fps:
        print(f"  ⚠  target fps ({target_fps}) > source fps ({source_fps:.2f}); "
              f"clamping to source fps.")
        target_fps = source_fps

    sample_indices = _source_frame_indices(source_fps, source_count, target_fps)
    n_out          = len(sample_indices)
    needed_set     = set(sample_indices)

    proc_dir = os.path.join(temp_folder, "processed")
    os.makedirs(proc_dir, exist_ok=True)

    print(f"\n[1/3] Extracting frames")
    print(f"      Source  : {orig_w}×{orig_h} @ {source_fps:.2f} fps  ({source_count} frames)")
    print(f"      Output  : {out_w}×{out_h} @ {target_fps:.2f} fps  ({n_out} frames)")
    print(f"      BG remov: {'ON' if remove_bg else 'OFF'}")

    # Read needed source frames in a single sequential pass (fast)
    raw_frames: dict[int, object] = {}
    src_idx = 0
    while src_idx <= max(sample_indices):
        ret, frame = cap.read()
        if not ret:
            break
        if src_idx in needed_set:
            raw_frames[src_idx] = frame.copy()
        src_idx += 1
    cap.release()

    frame_infos: list[FrameInfo] = []
    pad = max(3, len(str(n_out - 1)))
    t0  = time.monotonic()

    for out_idx, sidx in enumerate(sample_indices):
        raw = raw_frames.get(sidx)
        if raw is None:
            raise RuntimeError(
                f"Source frame {sidx} was not captured.  "
                f"The video may be shorter than expected."
            )

        proc_path       = os.path.join(proc_dir, f"frame_{out_idx:0{pad}d}.png")
        actual_w, actual_h = _save_frame(raw, scale, out_w, out_h, proc_path, remove_bg)
        frame_infos.append(FrameInfo(proc_path, actual_w, actual_h))
        _progress(out_idx + 1, n_out, prefix="frames")

    print()
    print(f"      Done – {n_out} frame(s) in {time.monotonic() - t0:.1f}s")
    return frame_infos, target_fps


# ═══════════════════════════════════════════════════════════════════════════════
# Step 2 – build the Lottie JSON structure
# ═══════════════════════════════════════════════════════════════════════════════

def _png_to_data_uri(path: str) -> str:
    """Read a PNG and return a data:image/png;base64,... URI string."""
    with open(path, "rb") as fh:
        b64 = base64.b64encode(fh.read()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def build_lottie_json(
    frames     : list[FrameInfo],
    target_fps : float,
) -> dict:
    """
    Build a Lottie JSON dict from scratch (no lottie-python animation object),
    giving us full control over every field.

    Lottie spec reference: https://lottie.github.io/lottie-spec/
    """
    if not frames:
        raise ValueError("frames list is empty.")

    n      = len(frames)
    width  = frames[0].width
    height = frames[0].height
    pad    = max(3, len(str(n - 1)))

    print(f"\n[2/3] Building Lottie JSON  ({n} frames @ {target_fps:.2f} fps  {width}×{height}) …")
    t0 = time.monotonic()

    assets : list[dict] = []
    layers : list[dict] = []

    for i, fi in enumerate(frames):
        asset_id = f"img_{i:0{pad}d}"

        # ── asset entry ───────────────────────────────────────────────────────
        assets.append({
            "id"  : asset_id,
            "w"   : fi.width,
            "h"   : fi.height,
            "u"   : "",                       # no file path; data inline
            "p"   : _png_to_data_uri(fi.path),
            "e"   : 1,                        # 1 = embedded (data URI)
        })

        # ── image layer ───────────────────────────────────────────────────────
        # Each layer is visible for exactly one frame: [i, i+1)
        layers.append({
            "ty"  : 2,                        # type 2 = image layer
            "nm"  : f"frame_{i:0{pad}d}",
            "refId": asset_id,
            "ind" : i,
            "st"  : 0,                        # stretch start
            "ip"  : i,                        # in point
            "op"  : i + 1,                    # out point
            "sr"  : 1,                        # stretch ratio
            "ks"  : _identity_transform(width, height),
            "ao"  : 0,                        # auto-orient
        })

        _progress(i + 1, n, prefix="layers ")

    print()
    print(f"      JSON built in {time.monotonic() - t0:.1f}s")

    lottie: dict = {
        "v"     : "5.9.0",                   # Lottie format version
        "nm"    : "video_to_lottie",
        "fr"    : target_fps,
        "ip"    : 0,                          # in point  (first frame)
        "op"    : n,                          # out point (exclusive)
        "w"     : width,
        "h"     : height,
        "assets": assets,
        "layers": layers,
        "meta"  : {
            "g" : "video_to_dotlottie",
        },
    }
    return lottie


def _identity_transform(width: int, height: int) -> dict:
    """
    Return a Lottie transform block that places the image at the canvas centre
    with no rotation, no skew, full opacity, and 100 % scale.

    Lottie image layers are anchored at their own centre, so the anchor point
    (a) and position (p) are both set to (w/2, h/2).
    """
    cx = width  / 2
    cy = height / 2
    return {
        "a" : {"a": 0, "k": [cx, cy, 0]},          # anchor
        "p" : {"a": 0, "k": [cx, cy, 0]},          # position
        "s" : {"a": 0, "k": [100, 100, 100]},       # scale (%)
        "r" : {"a": 0, "k": 0},                     # rotation
        "o" : {"a": 0, "k": 100},                   # opacity
        "sk": {"a": 0, "k": 0},                     # skew
        "sa": {"a": 0, "k": 0},                     # skew axis
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Step 3 – package / export
# ═══════════════════════════════════════════════════════════════════════════════

def export_as_dotlottie(lottie_json: dict, temp_folder: str,
                         output_filename: str) -> None:
    """Write a .lottie (zip) container."""
    json_path = os.path.join(temp_folder, "data.json")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(lottie_json, fh, separators=(",", ":"))   # compact JSON

    manifest = {
        "generator"  : "video_to_dotlottie",
        "version"    : "1.0",
        "animations" : [
            {
                "id"         : ANIM_ID,
                "speed"      : 1,
                "loop"       : True,
                "themeColor" : "#ffffff",
                "direction"  : 1,
            }
        ],
    }

    with zipfile.ZipFile(output_filename, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(json_path, f"animations/{ANIM_ID}.json")
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))

    size_mb = os.path.getsize(output_filename) / (1024 * 1024)
    print(f"      Saved dotLottie → '{output_filename}'  ({size_mb:.2f} MB)")


def export_as_json(lottie_json: dict, output_filename: str) -> None:
    """Write a plain .json Lottie file."""
    with open(output_filename, "w", encoding="utf-8") as fh:
        json.dump(lottie_json, fh, separators=(",", ":"))

    size_mb = os.path.getsize(output_filename) / (1024 * 1024)
    print(f"      Saved Lottie JSON → '{output_filename}'  ({size_mb:.2f} MB)")


# ═══════════════════════════════════════════════════════════════════════════════
# Main pipeline
# ═══════════════════════════════════════════════════════════════════════════════

def video_to_dotlottie(
    video_path      : str,
    output_filename : str,
    temp_folder     : str   = "temp_processing",
    target_fps      : float = 12.0,
    scale           : float = 1.0,
    remove_bg       : bool  = True,
    keep_temp       : bool  = False,
    output_format   : str   = "lottie",   # "lottie" | "json"
) -> None:
    """
    Full pipeline: video → frames → (bg removal) → Lottie JSON → .lottie / .json

    Parameters
    ----------
    video_path      Input video file.
    output_filename Destination file (.lottie or .json).
    temp_folder     Working directory for intermediate files.
    target_fps      Output animation frame rate (e.g. 12, 24).
    scale           Frame resize factor (1.0 = original size).
    remove_bg       Run rembg background removal on every frame.
    keep_temp       Preserve temp_folder after conversion.
    output_format   "lottie" (zipped .lottie) or "json" (plain Lottie JSON).
    """
    banner("video → .lottie converter  (v2)")

    inspect_video(video_path)   # print info table; raises early if file is bad

    if os.path.exists(temp_folder):
        shutil.rmtree(temp_folder)
    os.makedirs(temp_folder)

    t_start = time.monotonic()
    try:
        frames, fps = extract_frames(
            video_path, temp_folder,
            target_fps=target_fps,
            scale=scale,
            remove_bg=remove_bg,
        )

        lottie_json = build_lottie_json(frames, fps)

        print(f"\n[3/3] Exporting '{output_filename}' …")
        if output_format == "json":
            export_as_json(lottie_json, output_filename)
        else:
            export_as_dotlottie(lottie_json, temp_folder, output_filename)

    finally:
        if not keep_temp and os.path.exists(temp_folder):
            shutil.rmtree(temp_folder)

    total = time.monotonic() - t_start
    banner(f"Done!  →  {output_filename}  ({total:.1f}s total)")


def banner(text: str) -> None:
    line = "─" * 60
    print(f"\n{line}\n  {text}\n{line}")


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def _cli() -> None:
    p = argparse.ArgumentParser(
        description="Convert a video to a dotLottie or Lottie JSON animation.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("input",  nargs="?", default="input.mp4",
                   help="Input video path")
    p.add_argument("output", nargs="?", default="my_animation.lottie",
                   help="Output file (.lottie or .json)")
    p.add_argument("--fps",       type=float, default=12.0,
                   help="Output animation frame rate (fps)")
    p.add_argument("--scale",     type=float, default=1.0,
                   help="Frame resize factor (e.g. 0.5 = half resolution)")
    p.add_argument("--no-rembg",  action="store_true",
                   help="Skip background removal")
    p.add_argument("--keep-temp", action="store_true",
                   help="Keep temporary processing folder")
    p.add_argument("--temp-dir",  default="temp_processing",
                   help="Temporary folder name")
    p.add_argument("--format",    choices=["lottie", "json"], default="lottie",
                   help="Output format: zipped dotLottie or plain JSON")
    p.add_argument("--inspect",   action="store_true",
                   help="Print video info and exit without converting")
    args = p.parse_args()

    if args.inspect:
        inspect_video(args.input)
        return

    video_to_dotlottie(
        video_path      = args.input,
        output_filename = args.output,
        temp_folder     = args.temp_dir,
        target_fps      = args.fps,
        scale           = args.scale,
        remove_bg       = not args.no_rembg,
        keep_temp       = args.keep_temp,
        output_format   = args.format,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Interactive UI
# ═══════════════════════════════════════════════════════════════════════════════

def run_interactive() -> None:
    banner("🎥  VIDEO → .LOTTIE  INTERACTIVE CONVERTER  v2")

    # ── input file ────────────────────────────────────────────────────────────
    raw = input("\n▶  Drag-and-drop your video (or type path): ").strip().strip("\"'")
    if not os.path.exists(raw):
        print(f"❌  File not found: {raw}")
        return

    # Probe the file and show info before asking any further questions
    try:
        info = inspect_video(raw)
    except (IOError, FileNotFoundError) as exc:
        print(f"❌  {exc}")
        return

    # ── output file ───────────────────────────────────────────────────────────
    out = input("\n💾  Output filename [animation.json/animation.lottie]: ").strip()
    if not out:
        out = "animation.lottie"
    if not (out.endswith(".lottie") or out.endswith(".json")):
        out += ".lottie"

    # ── output format ─────────────────────────────────────────────────────────
    fmt_raw = input("📦  Output format — (1) dotLottie zip  (2) plain JSON  [1]: ").strip()
    fmt     = "json" if fmt_raw == "2" else "lottie"

    # ── target fps  (default = min(source_fps, 24)) ───────────────────────────
    default_fps = min(info.fps, 24.0)
    fps_raw     = input(f"🎞  Output frame rate in fps (source: {info.fps:.2f}) [{default_fps:.0f}]: ").strip()
    try:
        target_fps = float(fps_raw) if fps_raw else default_fps
        if target_fps <= 0:
            raise ValueError
    except ValueError:
        print(f"⚠  Invalid fps; using {default_fps:.0f}.")
        target_fps = default_fps

    # ── scale  (default = suggested scale from resolution) ────────────────────
    default_scale = info.suggested_scale
    scl_raw = input(
        f"🔍  Scale factor 0.1–1.0  "
        f"(suggested {default_scale} for {info.quality_label}) [{default_scale}]: "
    ).strip()
    try:
        scale = float(scl_raw) if scl_raw else default_scale
        scale = max(0.05, min(scale, 1.0))
    except ValueError:
        print(f"⚠  Invalid scale; using {default_scale}.")
        scale = default_scale

    # ── background removal ────────────────────────────────────────────────────
    bg_raw    = input("✂  Remove background? (y/n) [y]: ").strip().lower()
    remove_bg = bg_raw != "n"

    # ── run ───────────────────────────────────────────────────────────────────
    video_to_dotlottie(
        video_path      = raw,
        output_filename = out,
        target_fps      = target_fps,
        scale           = scale,
        remove_bg       = remove_bg,
        output_format   = fmt,
        keep_temp       = False,
    )


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        _cli()
    else:
        try:
            run_interactive()
        except KeyboardInterrupt:
            print("\n\n👋  Cancelled.")
        except Exception as exc:
            print(f"\n\n💥  {exc}")
            raise