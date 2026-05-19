#!/usr/bin/env python3
"""
Replicate scene generator for Jerome Baker Comes to New York.

Reads the scene prompt library below, calls Replicate's image API
(default: black-forest-labs/flux-1.1-pro), and saves images into
../img/ using the exact filenames the index.html expects
(01-grand-central-a.jpg, 02-subway-a.jpg, ...).

Idempotent: skips any slot whose file already exists. Pass --force to
overwrite. Pass --scene NN to limit to one scene. Pass --slot a|b|c to
limit to one variant per scene.

Cost (approx, single image):
    flux-schnell       ~$0.003
    flux-dev           ~$0.025
    flux-1.1-pro       ~$0.040   (default — best photo quality)
    flux-1.1-pro-ultra ~$0.060
Full batch (40 images) on flux-1.1-pro ≈ $1.60.

Usage:
    export REPLICATE_API_TOKEN=r8_...
    pip install -r requirements.txt
    python tools/generate.py                       # all missing slots
    python tools/generate.py --scene 03            # only scene 03
    python tools/generate.py --slot a              # only the a slot of each scene
    python tools/generate.py --model schnell       # fast/cheap iteration
    python tools/generate.py --hero                # also (re)generate hero.jpg
    python tools/generate.py --hero-only           # just the hero image
    python tools/generate.py --dry-run             # print plan, don't call API
    python tools/generate.py --force --scene 04    # overwrite all 3 slots of scene 04
"""
from __future__ import annotations
import argparse
import os
import sys
import time
from pathlib import Path

try:
    import replicate
except ImportError:
    sys.stderr.write("Missing replicate package. Install with: pip install -r requirements.txt\n")
    sys.exit(1)

try:
    import requests
except ImportError:
    sys.stderr.write("Missing requests package. Install with: pip install -r requirements.txt\n")
    sys.exit(1)


# ─── Character consistency ──────────────────────────────────────────
# Detailed lock on the actual physical Jerome — see assets/jerome-reference.png
# for the source photo. Diffusion models have no cross-call memory, so this
# very specific description is the only lever for visual continuity across
# the 13 scenes.
JEROME = (
    "Jerome Baker: a single anthropomorphized 5.5-foot tall handblown "
    "translucent deep-amethyst-purple glass beaker bong, standing "
    "upright at human height. SHAPE: tall straight cylindrical neck "
    "(roughly 3.5x the base diameter in height) flaring slightly at "
    "the very top into a thick mouthpiece rim wrapped with a decorative "
    "purple glass coil. BASE: round spherical purple-glass beaker base. "
    "ACCENTS: a cluster of small dichroic iridescent glass marbles "
    "(blue, green, teal, pearlescent) attached to one side of the neck "
    "near the middle. SLIDE: a golden-yellow glass downstem and bowl "
    "protruding from the lower side of the neck. GLASS: translucent "
    "deep purple throughout, transparent enough that light passes "
    "through, smooth and polished — not opaque, not patterned. EFFECTS: "
    "internal LED lights glowing deep purple from inside the glass "
    "cavity, thin wisps of pale white smoke drifting from the top "
    "mouthpiece. He is treated as a tall purple guest character in the "
    "scene. Single subject. Always this exact piece, always purple."
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

# ─── Replicate model registry ───────────────────────────────────────
# Short aliases mapped to actual Replicate model identifiers. flux-1.1-pro
# is the default — best photo realism in the FLUX family. Schnell is the
# fast/cheap iteration option. Dev is the open-weights middle ground.
MODELS = {
    "pro":     "black-forest-labs/flux-1.1-pro",
    "ultra":   "black-forest-labs/flux-1.1-pro-ultra",
    "dev":     "black-forest-labs/flux-dev",
    "schnell": "black-forest-labs/flux-schnell",
    "sdxl":    "stability-ai/sdxl",
}

# Per-model approximate cost / image (USD). For run-cost estimation only.
COSTS = {
    "pro":     0.040,
    "ultra":   0.060,
    "dev":     0.025,
    "schnell": 0.003,
    "sdxl":    0.011,
}


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


def _input_for(model_alias: str, prompt: str, aspect_ratio: str) -> dict:
    """Build the input dict the chosen model expects. FLUX models accept
    aspect_ratio + output_format; SDXL needs width/height."""
    if model_alias in ("pro", "ultra", "dev", "schnell"):
        d = {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "output_format": "jpg",
            "output_quality": 92,
            "safety_tolerance": 5,
        }
        if model_alias == "schnell":
            d.pop("safety_tolerance", None)
        if model_alias == "ultra":
            d["raw"] = False
        return d
    if model_alias == "sdxl":
        # Map common AR strings to pixel dims for SDXL.
        sizes = {"16:9": (1344, 768), "4:3": (1152, 896), "1:1": (1024, 1024)}
        w, h = sizes.get(aspect_ratio, (1344, 768))
        return {"prompt": prompt, "width": w, "height": h, "num_inference_steps": 30}
    return {"prompt": prompt}


def _download(url_or_file, dest: Path) -> int:
    """Replicate returns either a URL string, a FileOutput object with
    .read(), or a list of those. Save whichever to dest. Returns bytes
    written."""
    target = url_or_file
    if isinstance(target, list):
        target = target[0]

    # Newer SDK: FileOutput with .read()
    if hasattr(target, "read"):
        data = target.read()
        dest.write_bytes(data)
        return len(data)

    url = str(target)
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    dest.write_bytes(r.content)
    return len(r.content)


def generate_one(prompt: str, dest: Path, model_alias: str, aspect_ratio: str, dry: bool) -> str:
    if dry:
        return f"[DRY] would generate → {dest.name}\n        {prompt[:120]}…"
    model = MODELS[model_alias]
    inp = _input_for(model_alias, prompt, aspect_ratio)
    # Replicate throttles to 6 req/min + 1 burst when account balance is
    # "low" (under ~$5 effective). Re-tries that respect the server's
    # Retry-After hint cover the tail of any batch run cleanly.
    max_attempts = 4
    for attempt in range(1, max_attempts + 1):
        try:
            output = replicate.run(model, input=inp)
            n = _download(output, dest)
            return f"  ✓ {dest.name}  ({n // 1024} KB)"
        except Exception as e:
            msg = str(e)
            is_429 = "429" in msg or "throttled" in msg.lower() or "rate limit" in msg.lower()
            if not is_429 or attempt == max_attempts:
                raise
            # Extract "resets in ~Xs" if present, else exponential backoff.
            wait = 12 * attempt
            import re
            m = re.search(r"in ~?(\d+)\s*s", msg)
            if m:
                wait = max(int(m.group(1)) + 2, 6)
            print(f"  ⟲ rate-limited (attempt {attempt}/{max_attempts}) — waiting {wait}s…")
            time.sleep(wait)
    raise RuntimeError("unreachable")


def main():
    p = argparse.ArgumentParser(
        description="Generate Jerome Baker scene images via Replicate (FLUX by default).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Models: pro (default) | ultra | dev | schnell | sdxl",
    )
    p.add_argument("--scene", help="Only this scene id (01-13)")
    p.add_argument("--slot", choices=["a", "b", "c"], help="Only this slot per scene")
    p.add_argument("--force", action="store_true", help="Overwrite existing files")
    p.add_argument("--hero", action="store_true", help="Also (re)generate img/hero.jpg")
    p.add_argument("--hero-only", action="store_true", help="Generate just the hero image")
    p.add_argument("--model", default="pro", choices=list(MODELS.keys()),
                   help="Replicate model alias")
    p.add_argument("--aspect", default="16:9", choices=["16:9", "4:3", "1:1"],
                   help="Aspect ratio (default 16:9 — matches hero + first slot)")
    p.add_argument("--dry-run", action="store_true", help="Print plan, don't call API")
    args = p.parse_args()

    here = Path(__file__).resolve().parent
    img_dir = here.parent / "img"
    img_dir.mkdir(exist_ok=True)

    if not args.dry_run and not os.environ.get("REPLICATE_API_TOKEN"):
        sys.stderr.write(
            "Missing REPLICATE_API_TOKEN env var.\n"
            "Get one at https://replicate.com/account/api-tokens then:\n"
            "    export REPLICATE_API_TOKEN=r8_...\n"
        )
        sys.exit(2)

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

    cost_per = COSTS.get(args.model, 0.04)
    total = len(plan) * cost_per

    print(f"Plan: {len(plan)} image(s) · model={MODELS[args.model]} · aspect={args.aspect}")
    print(f"Estimated cost: ${total:.2f}  (${cost_per:.3f}/image)")
    print()

    for i, (sid, slot, dest) in enumerate(plan, 1):
        label = "hero" if sid == "hero" else f"scene {sid} slot {slot}"
        print(f"[{i}/{len(plan)}] {label} → {dest.name}")
        prompt = build_prompt(sid, slot) if sid != "hero" else HERO_PROMPT
        try:
            line = generate_one(prompt, dest, args.model, args.aspect, args.dry_run)
            print(line)
        except Exception as e:
            print(f"  ✗ FAILED: {e}", file=sys.stderr)
        if not args.dry_run and i < len(plan):
            time.sleep(0.3)  # tiny throttle


if __name__ == "__main__":
    main()
