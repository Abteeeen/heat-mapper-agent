#!/usr/bin/env python3
"""Combine one or more clips sequentially inside a "terminal + live feed"
frame (dark log panel on the left, the clip itself letterboxed into a
framed panel on the right) -- the layout used in ShadeScout's teaser/demo
videos.

Each source clip keeps its own aspect ratio: it is scaled to fit inside the
video panel and letterboxed (never cropped or stretched), so combining
clips of different native resolutions does not distort any of them.

Usage:
    python3 tools/terminal_overlay_video.py config.json -o out.mp4

config.json:
{
  "title": "CLAUDE FABLE / CAMPAIGNS / SUNDIAL · DALLAS-FORT WORTH",
  "active_tab": "Census",
  "prompt": "sundial@fable-5 : ~ % fable census --metro dfw --sold 12mo",
  "disclaimer": ["line one", "line two"],
  "clips": [
    {
      "video": "path/to/clip1.mp4",
      "pill": "aerial scan · property located",
      "log": [["16:12:24.487", "INFO", "zillow sold feed · 1 property matched"], ...],
      "stats": [["SOLD PULLED", "500", "white"], ...]
    },
    ...
  ]
}

Requires ffmpeg/ffprobe on PATH and Pillow (pip install Pillow).
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1920, 1080
TOPBAR_H = 90
LEFT_W = 660
RECT = (660, 90, 1880, 990)  # x0, y0, x1, y1 -- video panel in the 1920x1080 canvas

FONT_DIR = "/usr/share/fonts/truetype/dejavu"
MONO = f"{FONT_DIR}/DejaVuSansMono.ttf"
SANS = f"{FONT_DIR}/DejaVuSans.ttf"
SANS_B = f"{FONT_DIR}/DejaVuSans-Bold.ttf"

BG = (9, 9, 13)
BLACK = (0, 0, 0)
WHITE = (235, 235, 240)
GRAY = (120, 122, 130)
DIM = (70, 72, 80)
CYAN = (86, 182, 224)
GREEN = (94, 214, 138)
YELLOW = (224, 186, 84)
RED = (224, 90, 90)
ORANGE = (224, 140, 70)
COLOR_NAMES = {"white": WHITE, "yellow": YELLOW, "green": GREEN, "gray": GRAY, "red": RED}


def _font(path, size):
    return ImageFont.truetype(path, size)


def _draw_topbar(d, title):
    d.rectangle([0, 0, W, TOPBAR_H], fill=BLACK)
    for i, c in enumerate([RED, YELLOW, GREEN]):
        cx = 28 + i * 26
        d.ellipse([cx - 7, TOPBAR_H // 2 - 7, cx + 7, TOPBAR_H // 2 + 7], fill=c)
    tf = _font(SANS_B, 20)
    tw = d.textlength(title, font=tf)
    d.text(((W - tw) / 2, TOPBAR_H / 2 - 12), title, font=tf, fill=(190, 192, 198))
    lf = _font(SANS_B, 16)
    lw = d.textlength("LIVE", font=lf)
    lx = W - 40 - lw
    d.ellipse([lx - 20, TOPBAR_H / 2 - 6, lx - 8, TOPBAR_H / 2 + 6], fill=RED)
    d.text((lx, TOPBAR_H / 2 - 10), "LIVE", font=lf, fill=RED)


def _draw_tabs(d, active):
    tabs = ["Census", "Flagged", "Reports", "Postcards"]
    tf = _font(SANS_B, 19)
    x, y = 28, TOPBAR_H + 22
    for t in tabs:
        color = WHITE if t == active else GRAY
        d.text((x, y), t, font=tf, fill=color)
        tw = d.textlength(t, font=tf)
        if t == active:
            d.rectangle([x, y + 28, x + tw, y + 31], fill=ORANGE)
        x += tw + 34


def _draw_terminal(d, prompt, lines):
    pf = _font(MONO, 16)
    lf = _font(MONO, 15)
    x, y = 28, TOPBAR_H + 70
    d.text((x, y), prompt, font=pf, fill=GREEN)
    y += 30
    d.line([x, y - 4, LEFT_W - 28, y - 4], fill=(30, 31, 36))
    y += 6
    level_colors = {"INFO": CYAN, "OK": GREEN, "WARN": YELLOW, "D": DIM}
    for ts, level, msg in lines:
        d.text((x, y), ts, font=lf, fill=DIM)
        lvl_x = x + 118
        d.text((lvl_x, y), level, font=lf, fill=level_colors.get(level, WHITE))
        d.text((lvl_x + 56, y), msg, font=lf, fill=(200, 202, 208) if level != "D" else GRAY)
        y += 21
    y += 8
    d.text((x, y), "$ ", font=pf, fill=GREEN)
    d.rectangle([x + 18, y + 2, x + 28, y + 18], fill=(200, 210, 200))


def _draw_stats(d, stats):
    x, y = 28, H - 130
    d.line([x, y - 14, LEFT_W - 28, y - 14], fill=(30, 31, 36))
    lf, nf = _font(SANS, 13), _font(SANS_B, 26)
    col_w = (LEFT_W - 56) / max(len(stats), 1)
    for i, (label, value, color) in enumerate(stats):
        cx = x + i * col_w
        d.text((cx, y), label, font=lf, fill=GRAY)
        d.text((cx, y + 20), str(value), font=nf, fill=COLOR_NAMES.get(color, WHITE))


def _draw_disclaimer(d, lines):
    df = _font(SANS, 12)
    y = H - 46
    for line in lines:
        d.text((28, y), line, font=df, fill=(60, 62, 68))
        y += 15


def _draw_video_frame(d):
    x0, y0, x1, y1 = RECT
    pad = 6
    d.rectangle([x0 - pad, y0 - pad, x1 + pad, y1 + pad], outline=(90, 92, 100), width=2)
    d.rectangle([x0 - pad - 2, y0 - pad - 2, x1 + pad + 2, y1 + pad + 2], outline=(30, 31, 36), width=1)


def _draw_pill(d, text):
    x0, y0, _, _ = RECT
    pf = _font(SANS_B, 15)
    tw = d.textlength(text, font=pf)
    px0, py0 = x0 + 20, y0 + 20
    d.rounded_rectangle([px0, py0, px0 + tw + 44, py0 + 34], radius=17, fill=(0, 0, 0, 200))
    d.ellipse([px0 + 12, py0 + 12, px0 + 22, py0 + 22], fill=ORANGE)
    d.text((px0 + 30, py0 + 8), text, font=pf, fill=WHITE)


def build_background(path, title, active_tab, prompt, log_lines, stats, disclaimer, pill_text):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im, "RGBA")
    _draw_topbar(d, title)
    _draw_tabs(d, active_tab)
    _draw_terminal(d, prompt, log_lines)
    _draw_stats(d, stats)
    _draw_disclaimer(d, disclaimer)
    _draw_video_frame(d)
    _draw_pill(d, pill_text)
    im.save(path)


def composite_clip(bg_png, video_path, out_path):
    x0, y0, x1, y1 = RECT
    rw, rh = x1 - x0, y1 - y0
    filt = (
        f"[1:v]scale={rw}:{rh}:force_original_aspect_ratio=decrease,"
        f"pad={rw}:{rh}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1[v];"
        f"[0:v][v]overlay={x0}:{y0}:shortest=1[outv]"
    )
    cmd = [
        "ffmpeg", "-y", "-loop", "1", "-i", str(bg_png), "-i", str(video_path),
        "-filter_complex", filt, "-map", "[outv]", "-map", "1:a",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
        "-c:a", "aac", "-shortest", str(out_path), "-loglevel", "error",
    ]
    subprocess.run(cmd, check=True)


def concat(parts, out_path):
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        for p in parts:
            f.write(f"file '{Path(p).resolve()}'\n")
        list_path = f.name
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
        "-c", "copy", str(out_path), "-loglevel", "error",
    ]
    subprocess.run(cmd, check=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("config", help="Path to JSON config describing the clips (see module docstring).")
    ap.add_argument("-o", "--output", default="combined.mp4")
    args = ap.parse_args()

    config = json.loads(Path(args.config).read_text())
    title = config["title"]
    active_tab = config.get("active_tab", "Census")
    prompt = config["prompt"]
    disclaimer = config.get("disclaimer", [])

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        parts = []
        for i, clip in enumerate(config["clips"]):
            bg_png = tmp / f"bg_{i}.png"
            build_background(
                bg_png, title, active_tab, prompt,
                clip["log"], clip["stats"], disclaimer, clip["pill"],
            )
            part_path = tmp / f"part_{i}.mp4"
            composite_clip(bg_png, clip["video"], part_path)
            parts.append(part_path)
        concat(parts, args.output)

    print(f"Wrote {args.output}")


if __name__ == "__main__":
    sys.exit(main())
