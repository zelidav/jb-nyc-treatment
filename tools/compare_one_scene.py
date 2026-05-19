#!/usr/bin/env python3
"""
Compare Option 1 (bg-remove + PIL composite) vs Option 2 (flux-redux) for
ONE scene — the Federal Building. Produces img/compare-option1.jpg and
img/compare-option2.jpg so we can decide which path is worth scaling to
all 13 scenes.

Reads REPLICATE_API_TOKEN from env. Cost ≈ $0.07/run.
"""
from __future__ import annotations
import base64
import io
import os
import sys
from pathlib import Path

import re
import time

try:
    import replicate
    import requests
    from PIL import Image
except ImportError as e:
    sys.stderr.write(f"Missing dep: {e}\nInstall: pip install -r requirements.txt\n")
    sys.exit(1)


def replicate_run_with_retry(model: str, input_dict: dict, max_attempts: int = 4):
    """replicate.run() that respects Replicate's 'rate limit resets in ~Xs' hint.
    Mirrors the retry helper in tools/generate.py."""
    for attempt in range(1, max_attempts + 1):
        try:
            return replicate.run(model, input=input_dict)
        except Exception as e:
            msg = str(e)
            is_429 = "429" in msg or "throttled" in msg.lower() or "rate limit" in msg.lower()
            if not is_429 or attempt == max_attempts:
                raise
            m = re.search(r"in ~?(\d+)\s*s", msg)
            wait = max(int(m.group(1)) + 2, 6) if m else 12 * attempt
            print(f"  ⟲ rate-limited on {model} (attempt {attempt}/{max_attempts}) — waiting {wait}s…")
            time.sleep(wait)
    raise RuntimeError("unreachable")


REPO = Path(__file__).resolve().parent.parent
REFERENCE_PATH = REPO / "assets" / "jerome-reference.png"
# Pre-processed transparent version committed alongside the source. Skipping
# Replicate bg-removal entirely — those endpoints have been unreliable.
REFERENCE_TRANSPARENT = REPO / "assets" / "jerome-reference-transparent.png"
IMG_DIR = REPO / "img"
IMG_DIR.mkdir(exist_ok=True)

# Universal style + scene description (matches the main generator's library).
STYLE = (
    "Cinematic documentary photograph, 35mm film grain, natural light, "
    "candid bystanders, authentic location, realistic photo not "
    "illustration, shallow depth of field, no text or watermarks."
)
SCENE_FEDERAL_NO_JEROME = (
    "Wide documentary photograph of the public plaza in front of 26 Federal "
    "Plaza in Lower Manhattan, the imposing federal building facade fills "
    "the background, gray daylight, a security guard in uniform visible to "
    "one side, the plaza otherwise mostly empty with negative space in the "
    "center foreground where a tall subject would stand. No people in the "
    "center of the frame. " + STYLE
)
SCENE_FEDERAL_WITH_JEROME = (
    "Wide documentary photograph at 26 Federal Plaza in Lower Manhattan. "
    "Jerome Baker, a 5-and-a-half-foot tall translucent deep-purple "
    "handblown glass beaker bong with a tall straight neck, decorative "
    "coil-wrap mouthpiece, dichroic glass marbles on the side, golden bowl, "
    "and round spherical purple base, standing alone on the public plaza "
    "facing the imposing federal building. Gray daylight, the building's "
    "stone facade fills the background. He is the single foreground "
    "subject. " + STYLE
)


def upload_to_replicate(path: Path) -> str:
    """Upload a local file to Replicate's files service and return its URL.
    Models accept either a public URL or a `replicate.files.create` URL."""
    with open(path, "rb") as f:
        f_obj = replicate.files.create(file=f)
    return f_obj.urls["get"]


def download_to(url_or_file, dest: Path) -> int:
    target = url_or_file
    if isinstance(target, list):
        target = target[0]
    if hasattr(target, "read"):
        data = target.read()
        dest.write_bytes(data)
        return len(data)
    r = requests.get(str(target), timeout=120)
    r.raise_for_status()
    dest.write_bytes(r.content)
    return len(r.content)


def remove_background(input_url: str) -> bytes:
    """Run bg-removal on a Replicate-hosted image and return PNG bytes.
    Tries a couple of models in case the primary one is unavailable."""
    candidates = [
        "cjwbw/rembg",
        "lucataco/remove-bg",
        "851-labs/background-remover",
    ]
    last_err = None
    for model in candidates:
        try:
            out = replicate.run(model, input={"image": input_url})
            target = out[0] if isinstance(out, list) else out
            if hasattr(target, "read"):
                return target.read()
            r = requests.get(str(target), timeout=120)
            r.raise_for_status()
            return r.content
        except Exception as e:
            print(f"  bg-removal model {model} failed: {e}")
            last_err = e
    raise last_err if last_err else RuntimeError("no bg-removal model available")


def gen_scene_background() -> Path:
    """Generate the federal-building plaza scene with NO Jerome in it."""
    out = replicate_run_with_retry(
        "black-forest-labs/flux-1.1-pro",
        {
            "prompt": SCENE_FEDERAL_NO_JEROME,
            "aspect_ratio": "16:9",
            "output_format": "jpg",
            "output_quality": 92,
            "safety_tolerance": 5,
            "prompt_upsampling": True,
        },
    )
    dest = IMG_DIR / "_compare-bg.jpg"
    download_to(out, dest)
    return dest


def composite(scene_path: Path, bong_png_bytes: bytes, out_path: Path) -> None:
    """Paste the transparent bong PNG onto the generated scene, center-bottom,
    sized to ~78% of scene height (matches a tall human-height subject)."""
    scene = Image.open(scene_path).convert("RGBA")
    bong = Image.open(io.BytesIO(bong_png_bytes)).convert("RGBA")

    scene_w, scene_h = scene.size
    bong_w, bong_h = bong.size

    target_h = int(scene_h * 0.78)
    scale = target_h / bong_h
    new_w = int(bong_w * scale)
    bong = bong.resize((new_w, target_h), Image.LANCZOS)

    # Center-bottom, with a small floor padding (4% of height)
    pos_x = (scene_w - new_w) // 2
    pos_y = scene_h - target_h - int(scene_h * 0.02)

    # Drop-shadow for grounding — soft, behind the bong
    shadow = Image.new("RGBA", scene.size, (0, 0, 0, 0))
    # Use the bong's alpha as the shadow shape, blurred and shifted down.
    from PIL import ImageFilter
    alpha = bong.split()[-1]
    shadow_layer = Image.new("RGBA", bong.size, (0, 0, 0, 0))
    shadow_layer.paste((0, 0, 0, 110), (0, 0), alpha)
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=18))
    shadow.alpha_composite(shadow_layer, dest=(pos_x + 8, pos_y + 14))

    scene = Image.alpha_composite(scene, shadow)
    scene.alpha_composite(bong, dest=(pos_x, pos_y))

    scene.convert("RGB").save(out_path, "JPEG", quality=92)


def option_2_redux(reference_url: str, out_path: Path) -> None:
    """Use flux-redux-dev: takes the reference image + a scene prompt and
    blends them. Less exact than compositing but lighting integration is
    handled by the model."""
    out = replicate_run_with_retry(
        "black-forest-labs/flux-redux-dev",
        {
            "redux_image": reference_url,
            "prompt": SCENE_FEDERAL_WITH_JEROME,
            "aspect_ratio": "16:9",
            "output_format": "jpg",
            "output_quality": 92,
        },
    )
    download_to(out, out_path)


def main():
    if not os.environ.get("REPLICATE_API_TOKEN"):
        sys.exit("Missing REPLICATE_API_TOKEN")
    if not REFERENCE_PATH.exists():
        sys.exit(f"Missing reference image at {REFERENCE_PATH}")

    print("Uploading reference image to Replicate (for option 2)…")
    ref_url = upload_to_replicate(REFERENCE_PATH)
    print(f"  → {ref_url}")

    # ─── Option 1: load pre-removed PNG → generate plaza scene → PIL composite
    print("\n[Option 1] loading pre-bg-removed Jerome…")
    if not REFERENCE_TRANSPARENT.exists():
        sys.exit(f"Missing {REFERENCE_TRANSPARENT}. Run the local bg-removal first.")
    bong_png_bytes = REFERENCE_TRANSPARENT.read_bytes()
    print(f"  → {len(bong_png_bytes) // 1024} KB transparent PNG")

    print("[Option 1] generating plaza background (no Jerome)…")
    bg = gen_scene_background()
    print(f"  → {bg.name}")

    print("[Option 1] compositing…")
    option1 = IMG_DIR / "compare-option1-composite.jpg"
    composite(bg, bong_png_bytes, option1)
    print(f"  ✓ {option1.name}  ({option1.stat().st_size // 1024} KB)")

    # ─── Option 2: flux-redux blend ─────────────────────────────────────────
    print("\n[Option 2] flux-redux blend with reference image…")
    option2 = IMG_DIR / "compare-option2-redux.jpg"
    try:
        option_2_redux(ref_url, option2)
        print(f"  ✓ {option2.name}  ({option2.stat().st_size // 1024} KB)")
    except Exception as e:
        print(f"  ✗ Option 2 failed: {e}", file=sys.stderr)
        print("  (Option 1 already saved — workflow will commit what we have)")

    print("\nDone. Compare:")
    print(f"  {option1}")
    print(f"  {option2}")


if __name__ == "__main__":
    main()
