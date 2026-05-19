#!/usr/bin/env python3
"""
Image-to-video generator for Jerome Baker Comes to New York.

Animates the composite stills in ../img/ via Replicate's I2V models, saving
short mp4 clips to ../img/videos/. Tuned for social-media samples — each
clip is ~5 seconds, 16:9, ready to be cropped to 9:16 later.

Models (pass --model):
    wan      → wan-video/wan-2.1-i2v-720p     ~$0.10/clip   (default)
    kling    → kwaivgi/kling-v1.6-pro         ~$0.40/clip
    kling-s  → kwaivgi/kling-v1.6-standard    ~$0.20/clip
    minimax  → minimax/video-01               ~$0.30/clip

Usage:
    export REPLICATE_API_TOKEN=r8_...
    pip install -r requirements.txt
    python tools/generate_videos.py --scene 03 --slot a       # one clip
    python tools/generate_videos.py --hot                     # 5 hand-picked
    python tools/generate_videos.py --all                     # 14 scenes
    python tools/generate_videos.py --model kling --hot       # premium quality
    python tools/generate_videos.py --dry-run --hot
"""
from __future__ import annotations
import argparse
import os
import re
import sys
import time
from pathlib import Path

try:
    import replicate
    import requests
except ImportError as e:
    sys.stderr.write(f"Missing dep: {e}\nInstall: pip install -r requirements.txt\n")
    sys.exit(1)


REPO = Path(__file__).resolve().parent.parent
IMG_DIR = REPO / "img"
VID_DIR = IMG_DIR / "videos"
VID_DIR.mkdir(exist_ok=True)


# ─── Replicate model registry ──────────────────────────────────────
# Verified Replicate I2V model paths. Default to kling-s — good cost/quality
# balance, well-supported. Add others as we verify their schemas.
MODELS = {
    "kling-s": "kwaivgi/kling-v1.6-standard",
    "kling":   "kwaivgi/kling-v1.6-pro",
    "minimax": "minimax/video-01",
    "pixverse": "pixverse/pixverse-v4",
}
COSTS = {  # rough per-clip estimates
    "kling-s": 0.20,
    "kling":   0.40,
    "minimax": 0.30,
    "pixverse": 0.10,
}


# ─── Per-scene motion prompts ─────────────────────────────────────
# Each entry maps "scene_id_slot" → motion description that drives the I2V
# model. Keep these short — I2V models do a few things well: slow camera
# moves, subtle subject motion (fog, smoke, hair), small ambient action in
# the background (people walking past, leaves rustling). They struggle
# with anything sudden or character-specific.
MOTION_PROMPTS = {
    # Wide cinematic moves
    "01_a": "Slow camera push-in toward Jerome standing in Grand Central, commuters walk past on either side, fog drifts gently from his stem, ambient terminal light",
    "01_b": "Camera tilts up slowly along Jerome's purple glass to the famous brass clock above, soft fog rising, dust motes in the cathedral light",
    "01_c": "Handheld documentary motion as commuters glance and react to Jerome standing in the concourse, candid double-takes",

    "02_a": "Static wide of Jerome at the subway turnstile, handler swiping a metro card, faint platform light flickering, fog gently drifting",
    "02_b": "Subway car interior, Jerome stationary in the center, train rocks subtly side to side, commuters move in the background, fog wisps drift",
    "02_c": "Tunnel lights flash past the train window, Jerome's purple reflection visible in the glass, ambient train motion",

    "03_a": "Slow dolly pull-back from Jerome standing alone on the Federal Plaza, his fog drifting upward, the building looming larger in frame as we retreat",
    "03_b": "Camera holds close on Jerome's purple glass and the JBD mark, the federal seal of the United States blurred in the background gently shifting focus",
    "03_c": "Static composition of Jerome and a security guard both facing the federal building, wordless, neither moves, fog drifts upward — the staredown",

    "04_a": "Jerome at the Empire State Building entrance, real tourists shuffle in the queue around him, security guard takes a step forward, deadpan tension",
    "04_b": "Slow push-in on the handler's hands arranging a bouquet of red and white roses down Jerome's stem, fog still curling through the rose stems",
    "04_c": "Jerome standing outside the Empire State Building on the sidewalk, roses in his stem, golden hour light, he stays still while pedestrians walk past",

    "05_a": "Wide of the Balthazar dining room, Jerome stationary at a banquette, waiters move in slow elegant arcs between tables, faint fog drifting over the bread basket",
    "05_b": "Slow zoom on the French waiter solemnly pouring sparkling water into Jerome's base from a glass carafe, water flows in slow motion, ambient bistro hum",
    "05_c": "Close on Jerome's fog drifting gently over a basket of warm bread and a small butter dish, late lunch light, atmospheric",

    "06_a": "Aerial drone shot rotating slowly around Jerome standing on Rockaway Beach, beachgoers move below, waves rolling onto the sand",
    "06_b": "Two women in colorful bikinis on either side of the purple bong, spraying Windex from blue bottles and wiping its glass with microfiber cloths in slow deliberate strokes — mimics applying suntan lotion to a beach companion. Deadpan composure. Only the two women and the bong in frame, no other figures.",
    "06_c": "Jerome facing the open ocean, waves rolling in continuously, late afternoon golden sun, fog wisp drifting from his stem in the sea breeze",

    "07_a": "Elevator doors slide open onto the Gansevoort rooftop, Jerome visible in the doorway, cocktail crowd turns to look",
    "07_b": "Magic hour hero shot — slow dolly around Jerome at the rooftop railing, Manhattan skyline behind, ambers and purples in the sky shift, fog wisp drifting",
    "07_c": "A cocktail napkin with a phone number written on it sits at Jerome's base, ambient bar lights blurred in the distance, paper trembles slightly in the breeze",

    "08_a": "Jerome at the bow of the orange Staten Island Ferry like a figurehead, water spray rises, Lower Manhattan skyline glides past behind him",
    "08_b": "Wide tracking shot with the Statue of Liberty on one side and Jerome on the other, the ferry moves steadily through the harbor",
    "08_c": "A tourist couple smiles and takes a phone selfie with Jerome on the ferry deck, candid, handler positions them, harbor light",

    "09_a": "Jerome stands at the Niagara Falls railing, the massive falls roaring behind him, his fog mixes with the actual mist rising from the water",
    "09_b": "Jerome in a blue plastic poncho aboard the Maid of the Mist boat, water spray sweeps across the frame, real tourists in matching ponchos react",
    "09_c": "Dueling-fog close-up: Jerome's stem-smoke meets the actual Niagara mist in mid-air, water droplets sparkling on his purple glass",

    "10_a": "Slow push-in on Jerome standing alone on the Albany Capitol steps, his fog drifting up against the gray stone, the visual statement of his return",
    "10_b": "Tight hold on Jerome's purple glass against the textured carved Capitol stone, the JBD mark catches a shaft of light",
    "10_c": "Jerome and his handler walk together past manicured hedges on the Capitol grounds, formal slow pace, no irony",

    "11_a": "Aerial drone slowly rotating over Jerome standing between two perfectly aligned rows of grape vines, late summer light, vineyard rolls to the horizon",
    "11_b": "Inside a winery tasting room, Jerome at the wooden bar, a sommelier pours wine into a real wine glass placed in front of him, slow elegant motion",
    "11_c": "Picnic table under a tree — Jerome at one end like a third guest, charcuterie board, wine bottle, two glasses, late afternoon light filtering through leaves",

    "12_a": "Jerome walks the elevated High Line path with the Hudson behind him and Chelsea buildings to one side, slow handheld documentary motion, golden light",
    "12_b": "Jerome stands beside an actual contemporary sculpture installation on the High Line, deliberate composition, the wind moves the leaves slightly",
    "12_c": "Sunset on the High Line — purple sky meeting Jerome's purple glass, his glow matches the dusk gradient, slow handheld push",

    "13_a": "Jerome being wheeled toward the JFK TSA podium on a luggage cart, real travelers in parallel lanes do double-takes, fluorescent terminal light, ambient airport bustle",
    "13_b": "Close on the TSA agent's gloved hand returning a boarding pass to the handler, slow motion, Jerome blurred in the background, fog drifts past",
    "13_c": "TSA supervisor passes a security wand slowly around Jerome's beaker base, ambient terminal sounds, the wand beeps faintly",

    "14_a": "Drone shot from above the GW Bridge — Jerome mid-span with the handler beside him, Manhattan skyline receding behind them, slow forward motion across the deck",
    "14_b": "Reverse angle approaching the New Jersey side of the GW Bridge, the green 'Welcome to New Jersey' highway sign emerges in frame, golden hour light",
    "14_c": "Hero shot at the NJ side — Jerome standing in front of the green 'Welcome to New Jersey' sign at full readability, his fog drifts upward, slow pull-back as cars roll past behind",

    "hero": "Jerome glows purple in the foreground of a busy night street, blurred Manhattan skyline behind, light trails sweep past, fog drifts steadily from his stem — cinematic title-card energy",
}

# Curated picks for `--hot` flag — the 5 strongest social-sample candidates.
HOT_PICKS = [
    ("03", "a"),  # Federal Building wide — the cultural statement
    ("04", "b"),  # Empire State flowers-in-stem — comedy
    ("06", "b"),  # Beach Windex bit — comedy
    ("07", "b"),  # Gansevoort magic hour — beauty shot
    ("14", "c"),  # GW Bridge NJ sign — conquest finale
]


def replicate_run_with_retry(model: str, inp: dict, max_attempts: int = 4):
    """Honour Replicate's 'in ~Xs' retry hint on 429s."""
    for attempt in range(1, max_attempts + 1):
        try:
            return replicate.run(model, input=inp)
        except Exception as e:
            msg = str(e)
            is_429 = "429" in msg or "throttled" in msg.lower() or "rate limit" in msg.lower()
            if not is_429 or attempt == max_attempts:
                raise
            m = re.search(r"in ~?(\d+)\s*s", msg)
            wait = max(int(m.group(1)) + 2, 8) if m else 15 * attempt
            print(f"  ⟲ rate-limited (attempt {attempt}/{max_attempts}) — waiting {wait}s…")
            time.sleep(wait)
    raise RuntimeError("unreachable")


def upload_image(path: Path) -> str:
    """Upload the still to Replicate's files endpoint and return the URL."""
    with open(path, "rb") as f:
        obj = replicate.files.create(file=f)
    return obj.urls["get"]


def input_for(model_alias: str, image_url: str, motion: str) -> dict:
    """Each I2V model has its own input schema. Map our common args."""
    if model_alias in ("kling", "kling-s"):
        return {
            "start_image": image_url,
            "prompt": motion,
            "duration": 5,
            "aspect_ratio": "16:9",
            "cfg_scale": 0.5,
        }
    if model_alias == "minimax":
        return {
            "first_frame_image": image_url,
            "prompt": motion,
            "prompt_optimizer": True,
        }
    if model_alias == "pixverse":
        return {
            "image": image_url,
            "prompt": motion,
            "aspect_ratio": "16:9",
            "duration": 5,
            "quality": "540p",
        }
    raise ValueError(f"Unknown model alias: {model_alias}")


def download_to(output, dest: Path) -> int:
    """Replicate I2V output is a URL or FileOutput. Save to mp4."""
    target = output
    if isinstance(target, list):
        target = target[0]
    if hasattr(target, "read"):
        data = target.read()
        dest.write_bytes(data)
        return len(data)
    r = requests.get(str(target), timeout=300)
    r.raise_for_status()
    dest.write_bytes(r.content)
    return len(r.content)


def still_path_for(scene_id: str, slot: str) -> Path:
    """Find the composite still that corresponds to scene_id+slot."""
    if scene_id == "hero":
        return IMG_DIR / "hero.jpg"
    # Need to find the slug — scan img/ for matching prefix.
    for p in IMG_DIR.glob(f"{scene_id}-*-{slot}.jpg"):
        return p
    raise FileNotFoundError(f"No still for scene {scene_id} slot {slot}")


def video_dest_path(scene_id: str, slot: str) -> Path:
    if scene_id == "hero":
        return VID_DIR / "hero.mp4"
    still = still_path_for(scene_id, slot)
    return VID_DIR / (still.stem + ".mp4")


def main():
    p = argparse.ArgumentParser(
        description="Generate I2V clips from the composite stills (social samples).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Models: wan (default) | kling | kling-s | minimax",
    )
    sel = p.add_mutually_exclusive_group()
    sel.add_argument("--scene", help="Generate just this scene id (01-14 or hero)")
    sel.add_argument("--hot", action="store_true", help="The 5 curated picks for social samples")
    sel.add_argument("--all", action="store_true", help="Every scene+slot in MOTION_PROMPTS")
    p.add_argument("--slot", choices=["a", "b", "c"], help="With --scene, only this slot")
    p.add_argument("--force", action="store_true", help="Overwrite existing mp4s")
    p.add_argument("--model", default="kling-s", choices=list(MODELS.keys()))
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    if not args.dry_run and not os.environ.get("REPLICATE_API_TOKEN"):
        sys.exit("Missing REPLICATE_API_TOKEN")

    # Build the plan
    plan: list[tuple[str, str]] = []  # (scene_id, slot)
    if args.hot:
        plan = list(HOT_PICKS)
    elif args.all:
        for key in MOTION_PROMPTS:
            if key == "hero":
                plan.append(("hero", ""))
            else:
                sid, slot = key.split("_")
                plan.append((sid, slot))
    elif args.scene:
        if args.scene == "hero":
            plan.append(("hero", ""))
        else:
            slots = [args.slot] if args.slot else ["a", "b", "c"]
            for sl in slots:
                plan.append((args.scene, sl))
    else:
        sys.exit("Pick one: --scene NN | --hot | --all")

    # Filter to those with motion prompts + existing stills + not-already-generated (unless --force)
    final_plan = []
    for sid, slot in plan:
        key = "hero" if sid == "hero" else f"{sid}_{slot}"
        if key not in MOTION_PROMPTS:
            print(f"  ⚠ no motion prompt for {key}, skipping")
            continue
        try:
            still = still_path_for(sid, slot)
        except FileNotFoundError as e:
            print(f"  ⚠ {e}, skipping")
            continue
        dest = video_dest_path(sid, slot)
        if dest.exists() and not args.force:
            continue
        final_plan.append((sid, slot, still, dest, MOTION_PROMPTS[key]))

    if not final_plan:
        print("Nothing to generate (all targeted mp4s exist; use --force to overwrite).")
        return

    cost = len(final_plan) * COSTS[args.model]
    print(f"Plan: {len(final_plan)} clip(s) · model={MODELS[args.model]}")
    print(f"Estimated cost: ${cost:.2f}  (${COSTS[args.model]:.2f}/clip)")
    print()

    for i, (sid, slot, still, dest, motion) in enumerate(final_plan, 1):
        label = "hero" if sid == "hero" else f"scene {sid} slot {slot}"
        print(f"[{i}/{len(final_plan)}] {label} → {dest.name}")
        print(f"    still: {still.name}")
        print(f"    motion: {motion[:90]}…")
        if args.dry_run:
            continue
        try:
            url = upload_image(still)
            output = replicate_run_with_retry(MODELS[args.model], input_for(args.model, url, motion))
            n = download_to(output, dest)
            print(f"    ✓ {n // 1024} KB")
        except Exception as e:
            print(f"    ✗ FAILED: {e}", file=sys.stderr)
        if i < len(final_plan):
            time.sleep(0.5)


if __name__ == "__main__":
    main()
