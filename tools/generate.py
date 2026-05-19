#!/usr/bin/env python3
"""
DALL-E scene generator for Jerome Baker Comes to New York.

Reads the scene prompt library below, calls the OpenAI image API, and
saves images into ../img/ using the exact filenames the index.html
expects (01-grand-central-a.jpg, 02-subway-a.jpg, ...).

Idempotent: skips any slot whose file already exists. Pass --force to
overwrite. Pass --scene NN to limit to one scene. Pass --slot a|b|c to
limit to one variant per scene.

Costs roughly $0.04/image on dall-e-3 standard (~$1.50 for the full
batch of 39 images), $0.08/image HD.

Usage:
    export OPENAI_API_KEY=sk-...
    pip install -r requirements.txt
    python tools/generate.py                       # all missing slots
    python tools/generate.py --scene 03            # only scene 03
    python tools/generate.py --slot a              # only the a slot of each scene
    python tools/generate.py --quality hd          # higher quality (2x cost)
    python tools/generate.py --model gpt-image-1   # use newer gpt-image-1
    python tools/generate.py --hero                # also regenerate img/hero.jpg
    python tools/generate.py --dry-run             # print plan, don't call API
"""
from __future__ import annotations
import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path

try:
    from openai import OpenAI
except ImportError:
    sys.stderr.write("Missing openai package. Install with: pip install -r requirements.txt\n")
    sys.exit(1)

try:
    import requests
except ImportError:
    sys.stderr.write("Missing requests package. Install with: pip install -r requirements.txt\n")
    sys.exit(1)


# ─── Character consistency ──────────────────────────────────────────
# Same Jerome description prepended to every prompt so DALL-E renders a
# recognizably-similar character across scenes. The model doesn't have
# true cross-generation memory, so the more detail in the description,
# the more consistent the output.
JEROME = (
    "Jerome Baker: a single anthropomorphized 5.5-foot tall handblown "
    "translucent purple glass bong, smooth ornate craftsmanship with "
    "subtle decorative coils, internal LED lights glowing deep purple "
    "from inside the glass, thin wisps of pale smoke drifting from the "
    "top stem, treated as a tall guest character standing upright at "
    "human height. Single subject. Always purple, always glowing."
)

# Universal style. Pinned to a documentary / gonzo travel-doc aesthetic.
STYLE = (
    "Cinematic documentary photograph, 35mm film grain, natural light, "
    "candid bystanders, authentic location, realistic photo not "
    "illustration, shallow depth of field, no text or watermarks."
)

# ─── Scene library ──────────────────────────────────────────────────
# Each entry has a base prompt; the a/b/c variants tweak angle/moment.
SCENES = {
    "01": {
        "slug": "grand-central",
        "base": "Inside Grand Central Terminal main concourse at rush hour, golden cathedral light through arched windows, the famous brass clock visible.",
        "variants": {
            "a": "Wide establishing shot from the staircase looking down across the marble floor, Jerome standing in the center of frame, commuters mid-stride blurred around him.",
            "b": "Ground-up angle, Jerome positioned directly beneath the famous four-faced brass clock, dramatic perspective, ceiling visible.",
            "c": "Close-up reaction shot — tourists and businesspeople doing double-takes as Jerome stands beside them, candid expressions.",
        },
    },
    "02": {
        "slug": "subway",
        "base": "New York subway, gritty fluorescent light, tiled platform and steel subway car interior.",
        "variants": {
            "a": "Subway turnstile — Jerome squeezing through, handler swiping a metro card, fluorescent station light.",
            "b": "Inside a 6-train car, Jerome standing holding the center pole, commuters in seats giving him sidelong looks, daylight visible through windows.",
            "c": "Jerome's reflection in the window of a moving subway car as the tunnel goes dark, his purple internal LEDs the brightest thing in the frame.",
        },
    },
    "03": {
        "slug": "federal-building",
        "base": "26 Federal Plaza in Lower Manhattan, the imposing federal building facade, public plaza in front, gray daylight.",
        "variants": {
            "a": "Wide shot — Jerome standing alone on the public plaza facing the federal building, the building filling the background, the visual statement.",
            "b": "Close-up — the JBD mark visible on Jerome's purple glass, the federal seal of the United States blurred in the background behind him.",
            "c": "A security guard in uniform standing beside Jerome on the plaza, both facing the building, the handler watching from the side — wordless confrontation.",
        },
    },
    "04": {
        "slug": "empire-state",
        "base": "Empire State Building lobby entrance, art deco architecture, security checkpoint, queue of tourists.",
        "variants": {
            "a": "Jerome in line at the Empire State entrance with actual tourists ahead and behind, looking exactly like a five-foot glowing purple bong, security guard approaching.",
            "b": "Comedic moment — handler stuffing a large bouquet of red and white roses down Jerome's stem like a vase, fog still curling through the flowers, security guard skeptical in foreground.",
            "c": "Jerome standing outside the Empire State Building on the sidewalk after being denied entry, full bouquet of roses still in his stem, looking wistfully up at the tower.",
        },
    },
    "05": {
        "slug": "balthazar",
        "base": "Balthazar restaurant SoHo interior, classic French bistro, brass and mirrors, white tablecloths, banquette seating, mid-day diners.",
        "variants": {
            "a": "Wide of the dining room — Jerome occupying a banquette at table 14, menu placed in front of him, diners at adjacent tables glancing over, waiters moving past.",
            "b": "Solemn close-up of a French waiter in a black vest pouring sparkling water into Jerome's base from a glass carafe with perfect composure.",
            "c": "Smoke from the fog machine drifting gently over a bread basket and butter dish at Jerome's table, late lunch light through the windows.",
        },
    },
    "06": {
        "slug": "beach",
        "base": "Rockaway Beach New York on a sunny summer afternoon, white sand, blue Atlantic, beach umbrellas and casual beachgoers.",
        "variants": {
            "a": "Wide drone-style aerial — Jerome standing upright on the sand surrounded by colorful beach umbrellas and normal beachgoers, his purple glass catching the sunlight.",
            "b": "Handler in swim trunks calmly applying sunscreen to Jerome's glass base, deadpan, towel laid out, beach chair beside.",
            "c": "Jerome facing the open ocean, waves rolling in, late afternoon sun, fog wisp visible drifting from his stem against the sky.",
        },
    },
    "07": {
        "slug": "gansevoort",
        "base": "The Gansevoort hotel rooftop bar in the Meatpacking District at golden hour, Manhattan skyline visible, cocktail crowd in summer attire.",
        "variants": {
            "a": "Elevator doors opening onto the rooftop bar — Jerome stepping out (well-positioned), warm pendant lights, cocktail crowd turning to look.",
            "b": "Magic-hour hero shot — Jerome at the rooftop railing, Manhattan skyline behind, his purple glass and internal LEDs warm against the amber sunset sky, thin smoke curling.",
            "c": "Detail shot — a cocktail napkin tucked at Jerome's base with a phone number written on it in pen, ambient bar lights blurred.",
        },
    },
    "08": {
        "slug": "ferry",
        "base": "Staten Island Ferry, the bright orange double-decker boat, Lower Manhattan and the Statue of Liberty in the harbor.",
        "variants": {
            "a": "Jerome standing at the bow of the orange ferry like a figurehead, fog drifting, Lower Manhattan skyline behind, water spray.",
            "b": "Wide framing with the Statue of Liberty on one side of the frame and Jerome on the other side — two icons, equal compositional weight.",
            "c": "A tourist couple taking a smiling selfie with Jerome on the ferry deck, candid, handler positioning them, harbor light.",
        },
    },
    "09": {
        "slug": "niagara",
        "base": "Niagara Falls New York side, massive waterfall with rising mist, the iconic Maid of the Mist tour boat in the foreground with passengers in blue ponchos.",
        "variants": {
            "a": "Jerome standing at the railing in front of the falls, purple glass wet with mist, the roaring water and rainbow behind him, dramatic scale.",
            "b": "Jerome wearing a blue plastic poncho aboard the Maid of the Mist boat among real tourists in matching ponchos, the falls towering behind.",
            "c": "Comedic dueling-fog shot — Jerome's stem-smoke meeting the actual Niagara mist mid-air, water droplets sparkling on his purple glass.",
        },
    },
    "10": {
        "slug": "albany",
        "base": "New York State Capitol building in Albany — the historic stone capitol with its ornate facade and grand front steps.",
        "variants": {
            "a": "Wide shot of Jerome standing alone on the Capitol steps, fog drifting from his stem, his purple glow against the gray stone, the visual statement of his return.",
            "b": "Tight close-up of Jerome's purple glass against the textured carved stone of the Capitol facade, the JBD mark catching the light.",
            "c": "Jerome and his handler walking the Capitol grounds together past manicured hedges, a formal tour conducted without irony, government building backdrop.",
        },
    },
    "11": {
        "slug": "finger-lakes",
        "base": "Finger Lakes wine country in upstate New York, lush summer afternoon, rolling vineyards, blue sky.",
        "variants": {
            "a": "Aerial drone view of Jerome standing between two perfectly aligned rows of grape vines, the Finger Lakes vineyard stretching to the horizon.",
            "b": "Inside a winery tasting room, Jerome at the wooden tasting bar with a real wine glass placed in front of him, sommelier mid-explanation behind the counter.",
            "c": "Picnic table under a tree with a charcuterie board, wine bottle, and two wine glasses; Jerome positioned at one end of the table like a third guest.",
        },
    },
    "12": {
        "slug": "high-line",
        "base": "The High Line elevated park in Manhattan, the linear pathway with native plantings, with the Hudson and Chelsea cityscape visible.",
        "variants": {
            "a": "Jerome walking the path of the High Line with the Hudson River behind him and Chelsea buildings to one side, late afternoon light.",
            "b": "Jerome positioned beside an actual contemporary sculpture installation on the High Line, deliberate comparison composition.",
            "c": "Sunset shot — purple sky meeting Jerome's purple glass, his LEDs warm and matching the dusk gradient, the elevated walkway disappearing into the distance.",
        },
    },
    "13": {
        "slug": "sendoff",
        "base": "Nighttime in Manhattan, a black Town Car parked at a curb, a custom road case open beside it.",
        "variants": {
            "a": "Ceremonial wide shot — Jerome being placed into a padded custom road case at night, the handler easing him in, headlights of the waiting Town Car illuminating the scene.",
            "b": "Tight close-up of latches on the foam-padded road case snapping shut over Jerome's purple glass, dramatic shadow.",
            "c": "Wide rear-three-quarter shot of the black Town Car pulling away down an empty Manhattan street at night, taillights bright, Jerome's case in the trunk.",
        },
    },
}

HERO_PROMPT = (
    "A dramatic editorial photograph of Jerome Baker — a single "
    "anthropomorphized 5.5-foot tall handblown translucent purple glass "
    "bong with deep purple internal LED glow and thin smoke drifting from "
    "the stem — standing proudly in the foreground at street level "
    "in front of an iconic blurred New York City night skyline. "
    "Cinematic 35mm film aesthetic, shallow depth of field, single hero "
    "subject, no text, no watermarks."
)


def out_path(img_dir: Path, scene_id: str, slot: str, slug: str, hero: bool = False) -> Path:
    if hero:
        return img_dir / "hero.jpg"
    return img_dir / f"{scene_id}-{slug}-{slot}.jpg"


def build_prompt(scene_id: str, slot: str) -> str:
    if scene_id == "hero":
        return HERO_PROMPT
    s = SCENES[scene_id]
    return (
        f"{JEROME}\n\n"
        f"Scene: {s['base']}\n\n"
        f"Shot: {s['variants'][slot]}\n\n"
        f"Style: {STYLE}"
    )


def generate_one(client: OpenAI, prompt: str, dest: Path, model: str, quality: str, size: str, dry: bool) -> str:
    if dry:
        return f"[DRY] would generate → {dest.name}\n        {prompt[:120]}…"
    kwargs = dict(model=model, prompt=prompt, size=size, n=1)
    # quality flag works on dall-e-3; gpt-image-1 uses 'high'/'medium'/'low'
    if model == "dall-e-3":
        kwargs["quality"] = quality  # "standard" or "hd"
        kwargs["response_format"] = "url"
    elif model == "gpt-image-1":
        kwargs["quality"] = {"standard": "medium", "hd": "high"}.get(quality, "high")
    resp = client.images.generate(**kwargs)
    img = resp.data[0]
    if getattr(img, "url", None):
        r = requests.get(img.url, timeout=60)
        r.raise_for_status()
        dest.write_bytes(r.content)
    elif getattr(img, "b64_json", None):
        dest.write_bytes(base64.b64decode(img.b64_json))
    else:
        raise RuntimeError("OpenAI returned no url or b64_json")
    return f"  ✓ {dest.name}  ({dest.stat().st_size // 1024} KB)"


def main():
    p = argparse.ArgumentParser(description="Generate Jerome Baker scene images via DALL-E.")
    p.add_argument("--scene", help="Only this scene id (01-13)")
    p.add_argument("--slot", choices=["a", "b", "c"], help="Only this slot per scene")
    p.add_argument("--force", action="store_true", help="Overwrite existing files")
    p.add_argument("--hero", action="store_true", help="Also (re)generate img/hero.jpg")
    p.add_argument("--hero-only", action="store_true", help="Generate just the hero image")
    p.add_argument("--model", default="dall-e-3", choices=["dall-e-3", "gpt-image-1"])
    p.add_argument("--quality", default="standard", choices=["standard", "hd"])
    p.add_argument("--size", default="1792x1024", help="DALL-E size. 1792x1024 (landscape), 1024x1792 (portrait), 1024x1024")
    p.add_argument("--dry-run", action="store_true", help="Print plan, don't call API")
    args = p.parse_args()

    here = Path(__file__).resolve().parent
    img_dir = here.parent / "img"
    img_dir.mkdir(exist_ok=True)

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key and not args.dry_run:
        sys.stderr.write("Missing OPENAI_API_KEY env var.\n")
        sys.exit(2)
    client = OpenAI(api_key=api_key) if not args.dry_run else None

    plan: list[tuple[str, str, Path]] = []  # (scene_id, slot, dest)

    if args.hero or args.hero_only:
        dest = out_path(img_dir, "hero", "", "", hero=True)
        if args.force or not dest.exists():
            plan.append(("hero", "", dest))

    if not args.hero_only:
        scene_ids = [args.scene] if args.scene else sorted(SCENES.keys())
        for sid in scene_ids:
            if sid not in SCENES:
                sys.stderr.write(f"Unknown scene: {sid}\n"); continue
            slots = [args.slot] if args.slot else ["a", "b", "c"]
            for slot in slots:
                dest = out_path(img_dir, sid, slot, SCENES[sid]["slug"])
                if args.force or not dest.exists():
                    plan.append((sid, slot, dest))

    if not plan:
        print("Nothing to generate — all targeted slots already exist. (use --force to overwrite)")
        return

    est_cost_per = {"standard": 0.04, "hd": 0.08}.get(args.quality, 0.04)
    if args.model == "gpt-image-1":
        est_cost_per = 0.17  # rough — gpt-image-1 high is ~$0.17
    total = len(plan) * est_cost_per

    print(f"Plan: {len(plan)} image(s) · model={args.model} · quality={args.quality} · size={args.size}")
    print(f"Estimated cost: ${total:.2f}  (${est_cost_per:.2f}/image)")
    print()

    for i, (sid, slot, dest) in enumerate(plan, 1):
        label = f"hero" if sid == "hero" else f"scene {sid} slot {slot}"
        print(f"[{i}/{len(plan)}] {label} → {dest.name}")
        prompt = build_prompt(sid, slot) if sid != "hero" else HERO_PROMPT
        try:
            line = generate_one(client, prompt, dest, args.model, args.quality, args.size, args.dry_run)
            print(line)
        except Exception as e:
            print(f"  ✗ FAILED: {e}", file=sys.stderr)
        if not args.dry_run and i < len(plan):
            time.sleep(0.5)  # tiny throttle to be polite to the API


if __name__ == "__main__":
    main()
