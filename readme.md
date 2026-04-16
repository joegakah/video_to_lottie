# video_to_lottie

Convert any video file (MP4, MOV, AVI, …) into a **dotLottie** (`.lottie`) or plain **Lottie JSON** (`.json`) animation, with optional AI-powered background removal per frame.

---

## Features

- **FPS-based frame sampling** — specify the output frame rate independently of the source video; the sampler picks the nearest source frame for each target timestamp
- **WebP frame encoding** — frames are stored as WebP instead of PNG, giving ~25-40 % smaller output files with full RGBA transparency
- **Background removal** — powered by [rembg](https://github.com/danielgatis/rembg); remove backgrounds per-frame to produce clean transparent animations
- **Video inspection** — probe any video before conversion to see resolution, fps, duration, codec, bitrate, aspect ratio, and a recommended scale factor
- **Two output formats** — zipped `.lottie` container or plain `.json` Lottie file
- **Interactive mode** — guided prompts with smart defaults derived from the source video
- **CLI mode** — fully scriptable with all options exposed as flags

---

## Requirements

Install dependencies with:

```bash
pip install -r requirements.txt
```

The `rembg` package will download a background-removal model (~170 MB) on first use.

---

## Quick Start

### Interactive (recommended for first use)

```bash
python video_to_lottie.py
```

You'll be walked through each option. The tool probes your video first and suggests sensible defaults for scale and fps.

### Command line

```bash
python video_to_lottie.py input.mp4 output.lottie --fps 12 --scale 0.5
```

---

## CLI Reference

```
usage: video_to_lottie.py [input] [output] [options]
```

| Argument | Default | Description |
|---|---|---|
| `input` | `input.mp4` | Input video path |
| `output` | `my_animation.lottie` | Output file path |
| `--fps` | `12.0` | Output animation frame rate |
| `--scale` | `1.0` | Frame resize factor (e.g. `0.5` = half resolution) |
| `--webp-quality` | `80` | WebP encode quality 0-100 (`80` = good, `90` = near-lossless) |
| `--format` | `lottie` | Output format: `lottie` (zipped) or `json` (plain) |
| `--no-rembg` | off | Skip background removal (faster, no transparency) |
| `--keep-temp` | off | Preserve the temporary processing folder |
| `--temp-dir` | `temp_processing` | Name of the temporary folder |
| `--inspect` | off | Print video info and exit without converting |

### Examples

**Inspect a video without converting:**
```bash
python video_to_lottie.py myvideo.mp4 --inspect
```

**Convert at 24 fps, half resolution, no background removal:**
```bash
python video_to_lottie.py myvideo.mp4 out.lottie --fps 24 --scale 0.5 --no-rembg
```

**Export as plain Lottie JSON at near-lossless quality:**
```bash
python video_to_lottie.py myvideo.mp4 out.json --format json --webp-quality 90
```

**Maximum compression for a small web asset:**
```bash
python video_to_lottie.py myvideo.mp4 out.lottie --fps 10 --scale 0.25 --webp-quality 65
```

---

## Output Size Guide

Output file size is determined by three factors: frame count, resolution, and WebP quality. As a rough guide:

| Source | fps | Scale | Quality | Approx. size |
|---|---|---|---|---|
| 10s 1080p | 24 | 1.0 | 80 | ~40-80 MB |
| 10s 1080p | 12 | 0.5 | 80 | ~8-15 MB |
| 10s 1080p | 10 | 0.25 | 65 | ~1-3 MB |
| 5s 720p | 12 | 0.5 | 80 | ~3-6 MB |

**Tip:** For web use, `--fps 12 --scale 0.5 --webp-quality 80` is a good starting point. Run `--inspect` first to see the suggested scale for your specific video resolution.

---

## WebP Quality Settings

| Quality | Use case |
|---|---|
| 60-70 | Maximum compression, small logos or icons |
| 75-85 | Good balance for general web use *(default: 80)* |
| 85-93 | High-quality animations where detail matters |
| 94-100 | Near-lossless, large file size |

---

## How It Works

1. **Probe** — `inspect_video()` reads metadata via OpenCV and prints a summary table with a suggested scale factor based on resolution
2. **Extract** — frames are sampled from the source video at the requested fps using nearest-frame interpolation; only the needed frames are decoded (single sequential pass)
3. **Process** — each frame is optionally background-removed with rembg, converted to RGBA, and saved as WebP
4. **Build** — a Lottie JSON structure is assembled from scratch with correct `w`, `h`, `fr`, `ip`, `op` fields; each frame becomes one image asset + one image layer with explicit in/out points
5. **Export** — the JSON is either zipped into a `.lottie` container with a `manifest.json`, or written directly as a `.json` file

---

## Troubleshooting

**`rembg` is slow on first run**
The U2Net model (~170 MB) is downloaded on first use and cached in `~/.u2net/`. Subsequent runs are fast. For faster (lower quality) background removal you can experiment with `rembg`'s `--model` option.

**Output is very large**
Lower `--fps`, `--scale`, and/or `--webp-quality`. Run `--inspect` to see how many total frames would be produced at your chosen fps.

**`target fps > source fps` warning**
You requested a higher fps than the source video has. The tool automatically clamps to the source fps — no duplicate frames are inserted.

**`Source frame N was not captured`**
The video's reported frame count doesn't match its actual content (common with some encoders). Try re-encoding the source with FFmpeg: `ffmpeg -i input.mp4 -c copy fixed.mp4`.

**Background removal leaves artefacts**
Try `--scale 1.0` so rembg sees the full-resolution frame, then scale down. Background removal accuracy is significantly better at higher resolutions.