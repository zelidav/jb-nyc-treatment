#!/usr/bin/env python3
"""
Compare PIL-composite vs google/nano-banana for ONE scene (Federal Building).
nano-banana (Gemini 2.5 Flash Image on Replicate) accepts a reference image
plus a scene prompt and places the subject with proper scale + lighting —
in theory solving the perspective problem PIL compositing can't.

Cost: ~$0.04 per image. Outputs to img/compare-nb-*.jpg.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

try:
    import replicate
    import requests
except ImportError as e:
    sys.stderr.write(f"Missing dep: {e}\n"); sys.exit(1)

REPO = Path(__file__).resolve().parent.parent
REFERENCE = REPO / "assets" / "jerome-reference-transparent.png"
IMG_DIR = REPO / "img"
IMG_DIR.mkdir(exist_ok=True)


SCENE_PROMPT = (
    "Place the purple glass bong from the reference image standing on the "
    "public plaza in front of 26 Federal Plaza in Lower Manhattan. The "
    "bong is exactly 5 feet 6 inches tall — about the same height as a "
    "typical adult standing nearby. Render him at correct human scale: a "
    "passerby walking next to him should be roughly the same height. The "
    "imposing federal building fills the background, gray daylight, a "
    "security guard in uniform stands a few feet to one side, several "
    "pedestrians walk past at natural distance. Cinematic documentary "
    "photograph, 35mm film grain, natural light, realistic photo not "
    "illustration, no text or watermarks."
)


def upload(path: Path) -> str:
    with open(path, "rb") as f:
        obj = replicate.files.create(file=f)
    return obj.urls["get"]


def download_to(output, dest: Path) -> int:
    target = output
    if isinstance(target, list):
        target = target[0]
    if hasattr(target, "read"):
        data = target.read()
        dest.write_bytes(data)
        return len(data)
    r = requests.get(str(target), timeout=180)
    r.raise_for_status()
    dest.write_bytes(r.content)
    return len(r.content)


def main():
    if not os.environ.get("REPLICATE_API_TOKEN"):
        sys.exit("Missing REPLICATE_API_TOKEN")
    if not REFERENCE.exists():
        sys.exit(f"Missing reference: {REFERENCE}")

    print("Uploading Jerome reference to Replicate…")
    ref_url = upload(REFERENCE)
    print(f"  → {ref_url}")

    print("\nRunning google/nano-banana (Gemini 2.5 Flash Image)…")
    out = replicate.run(
        "google/nano-banana",
        input={
            "prompt": SCENE_PROMPT,
            "image_input": [ref_url],
            "output_format": "jpg",
            "aspect_ratio": "16:9",
        },
    )
    dest = IMG_DIR / "compare-nb-federal-building.jpg"
    n = download_to(out, dest)
    print(f"  ✓ {dest.name}  ({n // 1024} KB)")


if __name__ == "__main__":
    main()
