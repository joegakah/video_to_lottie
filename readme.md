# video_to_lottie

Convert any video file (MP4, MOV, AVI, …) into a **dotLottie** (`.lottie`) or plain **Lottie JSON** (`.json`) animation, with optional AI-powered background removal per frame.

---

## Features

- **FPS-based frame sampling** — specify output frame rate independently of the source video
- **WebP frame encoding** — ~25–40 % smaller output than PNG with full RGBA transparency
- **Background removal** — powered by [rembg](https://github.com/danielgatis/rembg); removes backgrounds per-frame for clean transparent animations
- **Video inspection** — probe any video before conversion: resolution, fps, duration, codec, bitrate, aspect ratio, and a recommended scale factor
- **Two output formats** — zipped `.lottie` container or plain `.json` Lottie file
- **Output folder** — all generated files are saved to an `output/` folder automatically created next to the script
- **Interactive mode** — guided prompts with smart defaults derived from the source video
- **CLI mode** — fully scriptable with all options as flags

---

## Setup

### 1. Clone or download the project

```bash
git clone https://github.com/yourname/video_to_lottie.git
cd video_to_lottie
```

### 2. Create a virtual environment

A virtual environment keeps the project's dependencies isolated from the rest of your system.

**macOS / Linux**
```bash
python3 -m venv venv
source venv/bin/activate
```

**Windows (Command Prompt)**
```cmd
python -m venv venv
venv\Scripts\activate.bat
```

**Windows (PowerShell)**
```powershell
python -m venv venv
venv\Scripts\Activate.ps1
```

You'll see `(venv)` at the start of your terminal prompt when the environment is active. Run `deactivate` to leave it.

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

> **Note:** `rembg` will download a background-removal model (~170 MB) on first use and cache it in `~/.u2net/`. Subsequent runs are fast.

### 4. Verify the install

```bash
python video_to_lottie.py --inspect input.mp4
```

---

## Usage

### Interactive (recommended for first use)

```bash
python video_to_lottie.py
```

You'll be prompted for each option. The tool probes your video first and suggests sensible defaults for scale and fps. When asked for the output file name, **enter just the name without an extension** (e.g. `my_animation`) — the correct extension (`.lottie` or `.json`) is added automatically based on the format you choose next.

### Command line

```bash
python video_to_lottie.py input.mp4 my_animation --fps 12 --scale 0.5
```

The output file is written to `output/my_animation.lottie` (or `.json` if `--format json`).

---

## Output

All converted files are saved to an **`output/`** folder created automatically next to `video_to_lottie.py`. You do not need to create it manually.

```
video_to_lottie/
├── video_to_lottie.py
├── requirements.txt
├── README.md
└── output/
    ├── my_animation.lottie
    └── another_clip.json
```

---

## CLI Reference

```
usage: video_to_lottie.py [input] [output] [options]
```

| Argument | Default | Description |
|---|---|---|
| `input` | `input.mp4` | Input video path |
| `output` | `my_animation` | Output file name — **no extension**, added automatically from `--format` |
| `--fps` | `12.0` | Output animation frame rate |
| `--scale` | `1.0` | Frame resize factor (e.g. `0.5` = half resolution) |
| `--webp-quality` | `80` | WebP encode quality 0–100 |
| `--format` | `lottie` | Output format: `lottie` (zipped) or `json` (plain) |
| `--no-rembg` | off | Skip background removal (faster, no transparency) |
| `--keep-temp` | off | Preserve the temporary processing folder after conversion |
| `--temp-dir` | `temp_processing` | Name of the temporary working folder |
| `--inspect` | off | Print video info and exit without converting |

### Examples

**Inspect a video without converting:**
```bash
python video_to_lottie.py myvideo.mp4 --inspect
```

**Convert at 24 fps, half resolution, no background removal:**
```bash
python video_to_lottie.py myvideo.mp4 my_anim --fps 24 --scale 0.5 --no-rembg
```

**Export as plain Lottie JSON:**
```bash
python video_to_lottie.py myvideo.mp4 my_anim --format json
```

**Maximum compression for a small web asset:**
```bash
python video_to_lottie.py myvideo.mp4 my_anim --fps 10 --scale 0.25 --webp-quality 65
```

---

## Output Size Guide

| Source | fps | Scale | Quality | Approx. size |
|---|---|---|---|---|
| 10s 1080p | 24 | 1.0 | 80 | ~40–80 MB |
| 10s 1080p | 12 | 0.5 | 80 | ~8–15 MB |
| 10s 1080p | 10 | 0.25 | 65 | ~1–3 MB |
| 5s 720p | 12 | 0.5 | 80 | ~3–6 MB |

For web use, `--fps 12 --scale 0.5 --webp-quality 80` is a good starting point. Run `--inspect` first to see the suggested scale for your specific video.

---

## WebP Quality Settings

| Quality | Use case |
|---|---|
| 60–70 | Maximum compression — small icons or logos |
| 75–85 | Good balance for general web use *(default: 80)* |
| 85–93 | High quality — detail matters |
| 94–100 | Near-lossless — large file size |

---

## How It Works

1. **Probe** — reads video metadata and prints a summary table with a suggested scale factor
2. **Extract** — samples frames at the requested fps using nearest-frame interpolation; only the needed frames are decoded in a single sequential pass
3. **Process** — each frame is optionally background-removed with rembg, converted to RGBA, and saved as WebP
4. **Build** — a Lottie JSON structure is assembled with correct `w`, `h`, `fr`, `ip`, `op` fields; each frame becomes one image asset and one image layer with explicit in/out points
5. **Export** — the JSON is zipped into a `.lottie` container or written as a plain `.json`, then saved to `output/`

---

## Troubleshooting

**`rembg` is slow on first run**
The U2Net model (~170 MB) downloads once and is cached in `~/.u2net/`.

**Output is very large**
Lower `--fps`, `--scale`, and/or `--webp-quality`. Run `--inspect` to see the total frame count before committing.

**`target fps > source fps` warning**
The tool clamps to the source fps automatically — no duplicate frames are inserted.

**`Source frame N was not captured`**
The video's reported frame count doesn't match its actual content (common with some encoders). Re-encode with FFmpeg first:
```bash
ffmpeg -i input.mp4 -c copy fixed.mp4
```

**Background removal leaves artefacts**
Try `--scale 1.0` so rembg sees full-resolution frames. Accuracy is significantly better at higher resolutions.

**`(venv)` disappeared from my prompt**
Your virtual environment was deactivated. Re-activate it:
```bash
# macOS / Linux
source venv/bin/activate

# Windows
venv\Scripts\activate.bat
```