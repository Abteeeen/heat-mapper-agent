#!/usr/bin/env python3
"""Combine one or more clips sequentially inside a "terminal + live feed"
frame (dark log panel on the left, the clip itself letterboxed into a
framed panel on the right) -- the layout used in ShadeScout's teaser/demo
videos.

The log panel is animated: lines stream in progressively over each clip's
own duration (like a live n8n execution log tailing in), ending on a
blinking cursor, instead of sitting there as one static frame.

Each source clip keeps its own aspect ratio: it is scaled to fit inside the
video panel and letterboxed (never cropped or stretched), so combining
clips of different native resolutions does not distort any of them.

Usage:
    python3 tools/terminal_overlay_video.py config.json -o out.mp4

config.json:
{
  "title": "CLAUDE FABLE / CAMPAIGNS / SUNDIAL · DALLAS-FORT WORTH",
  "active_tab": "Census",
  "prompt": "n8n ▸ shadescout · execution #482 · webhook received",
  "disclaimer": ["line one", "line two"],
  "clips": [
    {
      "video": "path/to/clip1.mp4",
      "pill": "n8n · imagery captured",
      "log": [["16:12:24.487", "INFO", "n8n · 1. RealtyAPI Search By Zip -> 200 OK"], ...],
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
FPS = 30

# reveal pacing: lines stream in over REVEAL_FRACTION of the clip's
# duration (leaving the tail for a blinking "still running" cursor),
# clamped to a sane per-line interval so a short clip doesn't reveal all
# its lines instantly and a long clip doesn't crawl.
REVEAL_FRACTION = 0.75
MIN_LINE_INTERVAL = 0.35
MAX_LINE_INTERVAL = 1.1
BLINK_PERIOD = 0.45

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


def _draw_terminal(d, prompt, lines, n_shown, show_bottom_prompt, cursor_on):
    """Draw the terminal panel with only `n_shown` of `lines` revealed.

    When `show_bottom_prompt` is True (all lines revealed), an extra
    "$ " row is drawn at the bottom with a blinking cursor block, so the
    panel reads as "still live" rather than finished/static.
    """
    pf = _font(MONO, 16)
    lf = _font(MONO, 15)
    x, y = 28, TOPBAR_H + 70
    d.text((x, y), prompt, font=pf, fill=GREEN)
    y += 30
    d.line([x, y - 4, LEFT_W - 28, y - 4], fill=(30, 31, 36))
    y += 6
    level_colors = {"INFO": CYAN, "OK": GREEN, "WARN": YELLOW, "D": DIM}
    for ts, level, msg in lines[:n_shown]:
        d.text((x, y), ts, font=lf, fill=DIM)
        lvl_x = x + 118
        d.text((lvl_x, y), level, font=lf, fill=level_colors.get(level, WHITE))
        d.text((lvl_x + 56, y), msg, font=lf, fill=(200, 202, 208) if level != "D" else GRAY)
        y += 21
    y += 8
    if show_bottom_prompt:
        d.text((x, y), "$ ", font=pf, fill=GREEN)
        if cursor_on:
            d.rectangle([x + 18, y + 2, x + 28, y + 18], fill=(200, 210, 200))
    else:
        # mid-stream: draw a steady (non-blinking) cursor right after the
        # last revealed line, so it reads as "still typing/streaming".
        d.rectangle([x, y + 2, x + 10, y + 18], fill=(200, 210, 200))


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


def render_frame(path, title, active_tab, prompt, log_lines, stats, disclaimer, pill_text,
                  n_shown, show_bottom_prompt, cursor_on):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im, "RGBA")
    _draw_topbar(d, title)
    _draw_tabs(d, active_tab)
    _draw_terminal(d, prompt, log_lines, n_shown, show_bottom_prompt, cursor_on)
    _draw_stats(d, stats)
    _draw_disclaimer(d, disclaimer)
    _draw_video_frame(d)
    _draw_pill(d, pill_text)
    im.save(path)


def probe_duration(video_path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
        check=True, capture_output=True, text=True,
    )
    return float(out.stdout.strip())


def build_reveal_schedule(duration, num_lines):
    """Return a list of (n_shown, show_bottom_prompt, cursor_on, seg_duration)."""
    if num_lines == 0:
        return [(0, True, True, duration)]

    interval = duration * REVEAL_FRACTION / num_lines
    interval = max(MIN_LINE_INTERVAL, min(MAX_LINE_INTERVAL, interval))

    schedule = []
    for k in range(num_lines):
        schedule.append((k, False, False, interval))
    reveal_elapsed = interval * num_lines
    remaining = max(0.0, duration - reveal_elapsed)

    cursor_on = True
    t = 0.0
    if remaining <= 0:
        # not enough tail for even one blink frame -- still show one so
        # the clip ends on the finished-log state.
        schedule.append((num_lines, True, True, max(0.05, duration - reveal_elapsed + 0.05)))
        return schedule
    while t < remaining:
        seg = min(BLINK_PERIOD, remaining - t)
        schedule.append((num_lines, True, cursor_on, seg))
        t += seg
        cursor_on = not cursor_on
    return schedule


def build_background_video(tmp, idx, duration, title, active_tab, prompt, log_lines, stats,
                            disclaimer, pill_text):
    schedule = build_reveal_schedule(duration, len(log_lines))
    list_path = tmp / f"bg_{idx}_list.txt"
    frames = []
    with open(list_path, "w") as f:
        for i, (n_shown, show_bottom_prompt, cursor_on, seg_dur) in enumerate(schedule):
            frame_path = tmp / f"bg_{idx}_{i}.png"
            render_frame(frame_path, title, active_tab, prompt, log_lines, stats, disclaimer,
                         pill_text, n_shown, show_bottom_prompt, cursor_on)
            frames.append(frame_path)
            f.write(f"file '{frame_path.name}'\n")
            f.write(f"duration {seg_dur:.3f}\n")
        # concat demuxer quirk: last entry's duration is ignored unless
        # followed by one more file line, so repeat the final frame.
        f.write(f"file '{frames[-1].name}'\n")

    bg_video = tmp / f"bg_{idx}.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_path),
         "-r", str(FPS), "-pix_fmt", "yuv420p", "-c:v", "libx264", "-crf", "16",
         str(bg_video), "-loglevel", "error"],
        check=True, cwd=tmp,
    )
    return bg_video


def composite_clip(bg_video, video_path, out_path):
    x0, y0, x1, y1 = RECT
    rw, rh = x1 - x0, y1 - y0
    filt = (
        f"[1:v]scale={rw}:{rh}:force_original_aspect_ratio=decrease,"
        f"pad={rw}:{rh}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1[v];"
        f"[0:v][v]overlay={x0}:{y0}:shortest=1[outv]"
    )
    cmd = [
        "ffmpeg", "-y", "-i", str(bg_video), "-i", str(video_path),
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
            duration = probe_duration(clip["video"])
            bg_video = build_background_video(
                tmp, i, duration, title, active_tab, prompt,
                clip["log"], clip["stats"], disclaimer, clip["pill"],
            )
            part_path = tmp / f"part_{i}.mp4"
            composite_clip(bg_video, clip["video"], part_path)
            parts.append(part_path)
        concat(parts, args.output)

    print(f"Wrote {args.output}")


if __name__ == "__main__":
    sys.exit(main())
