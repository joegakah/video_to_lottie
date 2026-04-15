import argparse
import json
import os
import shutil
import zipfile

import cv2
from PIL import Image as PILImage
from rembg import remove as rembg_remove

# ── lottie imports with unambiguous aliases ───────────────────────────────────
from lottie.objects import Animation
from lottie.objects import Image as LottieImageAsset   # FIX 1: renamed alias
from lottie.objects import ImageLayer as LottieImageLayer
from lottie.exporters import export_lottie

# The animation id must be consistent between the zip path and the manifest.
ANIM_ID = "animation"                                  # FIX 6


# ─────────────────────────────────────────────────────────────────────────────
def extract_frames(video_path: str, temp_folder: str,
                   max_frames: int | None = None,
                   scale: float = 1.0,
                   remove_bg: bool = True) -> tuple[list[str], float, int, int]:
    """
    Extract frames from *video_path*, optionally remove their backgrounds,
    and save them as frame_0.png, frame_1.png, … inside *temp_folder*.

    Returns (processed_paths, fps, frame_width, frame_height).
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise IOError(f"Cannot open video file: '{video_path}'")

    fps    = cap.get(cv2.CAP_PROP_FPS) or 30.0
    orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    width  = max(1, int(orig_w * scale))
    height = max(1, int(orig_h * scale))

    raw_dir  = os.path.join(temp_folder, "raw")
    proc_dir = os.path.join(temp_folder, "processed")
    os.makedirs(raw_dir,  exist_ok=True)
    os.makedirs(proc_dir, exist_ok=True)

    processed_paths: list[str] = []
    frame_idx = 0

    print(f"\n[1/3] Extracting frames from '{video_path}' …")
    print(f"      {orig_w}×{orig_h} @ {fps:.2f} fps  |  output: {width}×{height}"
          f"  |  bg-removal: {'on' if remove_bg else 'off'}")

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if max_frames is not None and frame_idx >= max_frames:
            break

        # ── save raw PNG ──────────────────────────────────────────────────────
        raw_path = os.path.join(raw_dir, f"frame_{frame_idx}.png")
        if scale != 1.0:
            frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
        cv2.imwrite(raw_path, frame)

        # ── optionally remove background ──────────────────────────────────────
        proc_path = os.path.join(proc_dir, f"frame_{frame_idx}.png")
        with PILImage.open(raw_path) as img:
            if remove_bg:
                out_img = rembg_remove(img)
            else:
                out_img = img.convert("RGBA")
            out_img.thumbnail((width, height))   # no-op if already smaller
            out_img.save(proc_path, "PNG")

        processed_paths.append(proc_path)
        frame_idx += 1

        if frame_idx % 10 == 0:
            print(f"      … {frame_idx} frames processed", end="\r")

    cap.release()
    print(f"      Extracted {len(processed_paths)} frame(s).        ")

    # re-read actual dimensions from the first processed frame
    if processed_paths:
        with PILImage.open(processed_paths[0]) as first:
            width, height = first.size

    return processed_paths, fps, width, height


# ─────────────────────────────────────────────────────────────────────────────
def build_lottie_animation(processed_paths: list[str],
                            fps: float, width: int, height: int) -> Animation:
    """
    Build a lottie.objects.Animation where each PNG frame is shown for
    exactly one Lottie frame.
    """
    n = len(processed_paths)
    if n == 0:
        raise ValueError("No processed frames found.")

    print(f"\n[2/3] Building Lottie animation  ({n} frames, {fps:.2f} fps, {width}×{height}) …")

    # FIX 2: n_frames = n (not n-1); FIX 7: set canvas size
    anim        = Animation(n, fps)
    anim.width  = width
    anim.height = height

    for i, path in enumerate(processed_paths):
        # FIX 3a: create an Image *asset* and embed the PNG via .load()
        asset    = LottieImageAsset()
        asset.load(path)          # embeds base64 data; sets id to filename stem
        asset.id = f"img_{i}"     # give it a predictable unique id

        anim.assets.append(asset)

        # FIX 3b: create an ImageLayer referencing the asset
        # FIX 4: set in_point / out_point BEFORE add_layer()
        layer           = LottieImageLayer(asset.id)
        layer.in_point  = i
        layer.out_point = i + 1

        anim.add_layer(layer)

        if (i + 1) % 10 == 0 or (i + 1) == n:
            print(f"      … {i + 1}/{n} layers built", end="\r")

    print(f"      Animation object ready.           ")
    return anim


# ─────────────────────────────────────────────────────────────────────────────
def package_dotlottie(anim: Animation, temp_folder: str, output_filename: str) -> None:
    """
    Export the Animation to JSON and package it into a .lottie (zip) file.
    """
    print(f"\n[3/3] Packaging '{output_filename}' …")

    json_path = os.path.join(temp_folder, "data.json")
    export_lottie(anim, json_path)

    # FIX 5: version must be a string
    # FIX 6: animation id matches the filename stem inside the zip
    manifest = {
        "generator" : "video_to_dotlottie",
        "version"   : "1.0",                        # FIX 5
        "animations": [
            {
                "id"         : ANIM_ID,              # FIX 6
                "speed"      : 1,
                "loop"       : True,
                "themeColor" : "#ffffff",
                "direction"  : 1
            }
        ]
    }

    with zipfile.ZipFile(output_filename, "w", zipfile.ZIP_DEFLATED) as zf:
        # FIX 6: filename inside zip matches ANIM_ID
        zf.write(json_path, f"animations/{ANIM_ID}.json")
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))

    size_mb = os.path.getsize(output_filename) / (1024 * 1024)
    print(f"      Saved → '{output_filename}'  ({size_mb:.2f} MB)")


# ─────────────────────────────────────────────────────────────────────────────
def video_to_dotlottie(
    video_path      : str,
    output_filename : str,
    temp_folder     : str  = "temp_processing",
    max_frames      : int | None = None,   # None = no limit
    scale           : float = 1.0,
    remove_bg       : bool  = True,
    keep_temp       : bool  = False,
) -> None:
    """
    Full pipeline: video → extract frames → (remove bg) → build Lottie → .lottie.

    Parameters
    ----------
    video_path       Path to the input video (mp4, mov, avi, …).
    output_filename  Destination .lottie file path.
    temp_folder      Working directory for intermediate files.
    max_frames       Cap on frames to process (None = all frames).
    scale            Resize factor, e.g. 0.5 = half resolution.
    remove_bg        Whether to run rembg background removal on each frame.
    keep_temp        If True, the temp_folder is not deleted after conversion.
    """
    print("=" * 60)
    print("  video → .lottie converter  (fixed)")
    print("=" * 60)

    # ── setup ─────────────────────────────────────────────────────────────────
    if os.path.exists(temp_folder):
        shutil.rmtree(temp_folder)
    os.makedirs(temp_folder)

    try:
        # ── step 1 ────────────────────────────────────────────────────────────
        paths, fps, w, h = extract_frames(
            video_path, temp_folder,
            max_frames=max_frames,
            scale=scale,
            remove_bg=remove_bg,
        )

        # ── step 2 ────────────────────────────────────────────────────────────
        anim = build_lottie_animation(paths, fps, w, h)

        # ── step 3 ────────────────────────────────────────────────────────────
        package_dotlottie(anim, temp_folder, output_filename)

    finally:
        if not keep_temp and os.path.exists(temp_folder):
            shutil.rmtree(temp_folder)
            print(f"\n      Temp folder '{temp_folder}' removed.")

    print("\n" + "=" * 60)
    print(f"  Done!  →  {output_filename}")
    print("=" * 60)


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────
def _cli() -> None:
    p = argparse.ArgumentParser(
        description="Convert a video to a dotLottie (.lottie) animation."
    )
    p.add_argument("input",  nargs="?", default="input.mp4",
                   help="Input video path (default: input.mp4)")
    p.add_argument("output", nargs="?", default="my_animation.lottie",
                   help="Output .lottie path (default: my_animation.lottie)")
    p.add_argument("--max-frames", type=int,   default=None,
                   help="Max frames to extract (default: all)")
    p.add_argument("--scale",      type=float, default=1.0,
                   help="Frame resize factor (default: 1.0)")
    p.add_argument("--no-rembg",   action="store_true",
                   help="Skip background removal (faster, no transparency)")
    p.add_argument("--keep-temp",  action="store_true",
                   help="Keep the temporary processing folder")
    p.add_argument("--temp-dir",   default="temp_processing",
                   help="Temp folder name (default: temp_processing)")
    args = p.parse_args()

    video_to_dotlottie(
        video_path      = args.input,
        output_filename = args.output,
        temp_folder     = args.temp_dir,
        max_frames      = args.max_frames,
        scale           = args.scale,
        remove_bg       = not args.no_rembg,
        keep_temp       = args.keep_temp,
    )

# ─────────────────────────────────────────────────────────────────────────────
# INTERACTIVE UI
# ─────────────────────────────────────────────────────────────────────────────
def run_interactive():
    print("=" * 60)
    print("  🎥 VIDEO TO .LOTTIE INTERACTIVE CONVERTER")
    print("=" * 60)

    # 1. Get File Path
    video_input = input("\n▶️ Drag and drop your video file here (or type path): ").strip().replace('"', '').replace("'", "")
    if not os.path.exists(video_input):
        print(f"❌ Error: Could not find file at {video_input}")
        return

    # 2. Get Output Name
    output_name = input("💾 Enter output filename (default: animation.lottie): ").strip()
    if not output_name:
        output_name = "animation.lottie"
    if not output_name.endswith(".lottie"):
        output_name += ".lottie"

    # 3. Settings
    try:
        scale_val = input("🔍 Scale factor (0.1 to 1.0) [default 0.5 for web]: ").strip()
        scale = float(scale_val) if scale_val else 0.5

        max_f_val = input("🎞️ Max frames to process (Enter for ALL): ").strip()
        max_frames = int(max_f_val) if max_f_val else None

        bg_choice = input("✂️ Remove background? (y/n) [default y]: ").strip().lower()
        remove_bg = False if bg_choice == 'n' else True
    except ValueError:
        print("⚠️ Invalid input detected. Using safe defaults.")
        scale, max_frames, remove_bg = 0.5, None, True

    # Run the main pipeline
    video_to_dotlottie(
        video_path      = video_input,
        output_filename = output_name,
        scale           = scale,
        max_frames      = max_frames,
        remove_bg       = remove_bg,
        keep_temp       = False
    )

if __name__ == "__main__":
    try:
        run_interactive()
    except KeyboardInterrupt:
        print("\n\n👋 Operation cancelled by user.")
    except Exception as e:
        print(f"\n\n💥 An unexpected error occurred: {e}")