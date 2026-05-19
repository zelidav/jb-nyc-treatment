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
    import requests
    from PIL import Image  # noqa: F401 — used by composite_jerome
except ImportError as e:
    sys.stderr.write(f"Missing dep: {e}\nInstall: pip install -r requirements.txt\n")
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
            "b": "TWO young women in colorful summer bikinis, both facing the bong, one on each side, calmly spraying Windex from blue bottles and wiping its purple glass with microfiber cloths — the gesture deliberately mimics rubbing sunscreen onto a beach companion. Deadpan composure. Beach towel and chair beside. STRICT: only the two women + the bong in the frame, NO MEN ANYWHERE in the scene, no male figures, no third person.",
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
        "slug": "jfk",
        "base": "JFK Airport Terminal 4 TSA security checkpoint, busy travelers in parallel lanes, x-ray belts, uniformed TSA agents, glass partitions, fluorescent terminal light.",
        "variants": {
            "a": "Jerome being wheeled toward the TSA podium on a luggage cart, real travelers in adjacent lanes doing double-takes, a uniformed TSA agent watching from behind the podium with neutral expression.",
            "b": "Close on the TSA agent's gloved hand returning a boarding pass to the handler — Jerome visible just behind them, fog drifting from his stem against the fluorescent light.",
            "c": "TSA supervisor passing a security wand around Jerome's beaker base, walkie-talkie in the foreground, glass partitions of the checkpoint visible behind.",
        },
    },
    "14": {
        "slug": "gw-bridge",
        "base": "The George Washington Bridge pedestrian path crossing the Hudson River, suspension cables overhead, late afternoon golden light, cars rolling past on the roadway.",
        "variants": {
            "a": "Drone shot from above the GW Bridge — Jerome mid-span on the pedestrian path with a handler beside him, the Manhattan skyline receding behind, the bridge cables forming a leading line.",
            "b": "Reverse angle approaching the New Jersey side of the GW Bridge — a green 'Welcome to New Jersey' highway sign visible ahead, Jerome's silhouette in the foreground, golden hour light.",
            "c": "Hero shot at the NJ side of the bridge — Jerome standing directly in front of the green 'Welcome to New Jersey' sign at full readability, fog drifting, the bridge stretching back toward Manhattan in the distance.",
        },
    },
    "15": {
        "slug": "syracuse",
        "base": "JMA Wireless Dome (formerly the Carrier Dome) in Syracuse, NY on a Saturday game day. Syracuse Orange football. Orange-clad fans everywhere, the iconic white dome roof, dome interior with bright stadium lights.",
        "variants": {
            "a": "Wide tailgate shot in the parking lot outside the dome — Jerome standing among a sea of Syracuse Orange fans in orange jerseys, grills smoking, painted faces, school flags, a cooler beside Jerome, late autumn upstate light.",
            "b": "Inside the JMA Wireless Dome during a Syracuse Orange football game — Jerome standing on the sideline near the end zone, the field and stands packed with orange-clad fans visible behind him, scoreboard glowing, stadium light.",
            "c": "Halftime hero shot — Jerome at the 50-yard line under the dome's white ceiling, the Orange marching band on the field behind him, fans on their feet in the stands, dramatic stadium light, ambient roar.",
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
# nano-banana (Gemini 2.5 Flash Image) is the default — it accepts the
# Jerome reference image directly and renders him into the scene at
# correct scale + lighting + integration in one pass. FLUX variants
# remain as fallbacks for text-only / non-reference generation.
MODELS = {
    "nb":      "google/nano-banana",
    "pro":     "black-forest-labs/flux-1.1-pro",
    "ultra":   "black-forest-labs/flux-1.1-pro-ultra",
    "dev":     "black-forest-labs/flux-dev",
    "schnell": "black-forest-labs/flux-schnell",
    "sdxl":    "stability-ai/sdxl",
}

# Per-model approximate cost / image (USD). For run-cost estimation only.
COSTS = {
    "nb":      0.040,
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


# Tight inline character description used in the SCENE-first prompt
# template. FLUX over-indexes on the first thing in the prompt — if the
# Jerome description leads, every output is a product shot of the bong.
# Leading with the scene + treating Jerome as a subject INSIDE that scene
# is what makes the model put him on the street instead of on a backdrop.
JEROME_INLINE = (
    "In the scene, standing upright at full human height like a tall "
    "purple guest character: a 5-and-a-half-foot anthropomorphized "
    "handblown translucent deep-amethyst-purple glass beaker bong with "
    "a long straight cylindrical neck, a decorative purple glass coil "
    "wrap at the flared mouthpiece, a small cluster of dichroic "
    "iridescent glass marbles (blue/green/teal/pearlescent) attached to "
    "the side of the neck, a golden-yellow glass downstem and bowl "
    "protruding from the lower side, and a round spherical purple-glass "
    "beaker base. Translucent deep purple throughout, faint internal "
    "purple LED glow, a thin wisp of pale smoke drifting from the top "
    "mouthpiece. He must be visible in the frame as a character inside "
    "the scene, not isolated on a studio backdrop."
)

def build_prompt(scene_id: str, slot: str) -> str:
    """Text-to-image prompt (Jerome described in the scene). Used when
    --no-composite is passed."""
    if scene_id == "hero":
        return HERO_PROMPT
    s = SCENES[scene_id]
    return (
        f"{s['base']} {s['variants'][slot]} "
        f"{JEROME_INLINE} "
        f"{STYLE}"
    )


def build_bg_prompt(scene_id: str, slot: str) -> str:
    """Background-only prompt — Jerome omitted entirely. Tells the model
    to leave negative space in the center foreground where we'll composite
    the real bong PNG. Crucially the scene must include people at normal
    adult height somewhere in the frame — without that, the composited
    Jerome reads as a monument instead of a 5-and-a-half-foot piece."""
    scale_ref = (
        "Include several people of normal adult height (5'6\"–6'0\") visible "
        "in the scene at natural scale — walking, standing, or interacting — "
        "so the viewer has clear human scale reference. Shot at human eye "
        "level, not from above. People should be in middle and far distance "
        "but NOT in the center foreground (leave the center foreground empty "
        "for a tall narrow subject)."
    )
    if scene_id == "hero":
        return (
            "A wide editorial photograph of a busy New York City night street "
            "with the iconic blurred Manhattan skyline behind. " + scale_ref +
            " " + STYLE
        )
    s = SCENES[scene_id]
    return (
        f"{s['base']} {s['variants'][slot]} "
        f"{scale_ref} "
        f"{STYLE}"
    )


# ─── Composite config ──────────────────────────────────────────────
# Where to place Jerome in each rendered scene. Calibrated so Jerome reads
# as a 5'6" piece, not a monument. Default scale is 0.55 of scene height —
# at 16:9 that puts him at roughly head-height for an adult standing nearby.
# Per-slot defaults adjust further: wide establishing shots smallest (still
# wants people nearby for reference), close-ups largest. Per scene+slot
# overrides handle aerials, off-center compositions, and hero shots.
COMPOSITE_DEFAULTS = {"scale": 0.55, "x_pct": 0.50, "y_pad_pct": 0.02}

SLOT_DEFAULTS = {
    "a": {"scale": 0.52},   # Wide establishing — Jerome at human scale next to people
    "b": {"scale": 0.58},   # Medium / "the bit" — slightly closer camera
    "c": {"scale": 0.66},   # Close-up / detail — camera tighter, he fills more frame
}

COMPOSITE_OVERRIDES: dict[str, dict] = {
    # Aerial / drone shots — Jerome much smaller, floating mid-frame
    "06_a": {"scale": 0.22, "x_pct": 0.50, "y_pad_pct": 0.42},   # Beach aerial
    "11_a": {"scale": 0.26, "x_pct": 0.50, "y_pad_pct": 0.32},   # Finger Lakes vineyard aerial
    "14_a": {"scale": 0.20, "x_pct": 0.50, "y_pad_pct": 0.45},   # GW Bridge drone mid-span
    # Detail close-ups where the bong fills more of the frame (camera close)
    "10_b": {"scale": 0.88, "x_pct": 0.50, "y_pad_pct": 0.02},   # Capitol stone close-up
    "03_b": {"scale": 0.78, "x_pct": 0.55, "y_pad_pct": 0.02},   # Federal seal close
    "05_b": {"scale": 0.62, "x_pct": 0.50, "y_pad_pct": 0.04},   # Waiter pouring close
    "07_c": {"scale": 0.40, "x_pct": 0.45, "y_pad_pct": 0.04},   # Cocktail napkin detail (smaller, off-center)
    # Off-center compositions
    "08_b": {"scale": 0.50, "x_pct": 0.72, "y_pad_pct": 0.04},   # Ferry: Liberty left, Jerome right
    "02_a": {"scale": 0.55, "x_pct": 0.38, "y_pad_pct": 0.04},   # Subway turnstile
    "12_b": {"scale": 0.50, "x_pct": 0.65, "y_pad_pct": 0.04},   # High Line beside installation
    # Hero / signature shots — slightly taller but still recognizably 5'6"
    "07_b": {"scale": 0.64, "x_pct": 0.50, "y_pad_pct": 0.02},   # Gansevoort magic hour hero
    "14_c": {"scale": 0.62, "x_pct": 0.50, "y_pad_pct": 0.02},   # GW Bridge NJ-sign hero
    "03_a": {"scale": 0.58, "x_pct": 0.50, "y_pad_pct": 0.02},   # Federal Plaza wide
    "10_a": {"scale": 0.55, "x_pct": 0.50, "y_pad_pct": 0.02},   # Capitol steps wide
}

def get_composite_cfg(scene_id: str, slot: str) -> dict:
    cfg = COMPOSITE_DEFAULTS.copy()
    # Apply slot-level default first, then any per-(scene,slot) override.
    cfg.update(SLOT_DEFAULTS.get(slot, {}))
    cfg.update(COMPOSITE_OVERRIDES.get(f"{scene_id}_{slot}", {}))
    return cfg


def composite_jerome(scene_path: Path, bong_png_bytes: bytes, out_path: Path,
                     scale: float, x_pct: float, y_pad_pct: float) -> None:
    """Paste the transparent bong PNG onto a generated scene with a soft drop
    shadow for grounding. Bong height = scale * scene_height. Horizontal anchor
    at x_pct of scene width (0.5 = center). Bottom edge sits y_pad_pct above
    the scene's bottom edge."""
    import io
    from PIL import Image, ImageFilter
    scene = Image.open(scene_path).convert("RGBA")
    bong = Image.open(io.BytesIO(bong_png_bytes)).convert("RGBA")

    scene_w, scene_h = scene.size
    bong_w, bong_h = bong.size

    target_h = int(scene_h * scale)
    factor = target_h / bong_h
    new_w = int(bong_w * factor)
    bong = bong.resize((new_w, target_h), Image.LANCZOS)

    pos_x = int(scene_w * x_pct - new_w / 2)
    pos_y = scene_h - target_h - int(scene_h * y_pad_pct)

    # Soft drop shadow under Jerome for visual grounding
    shadow = Image.new("RGBA", scene.size, (0, 0, 0, 0))
    alpha = bong.split()[-1]
    shadow_layer = Image.new("RGBA", bong.size, (0, 0, 0, 0))
    shadow_layer.paste((0, 0, 0, 115), (0, 0), alpha)
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=20))
    shadow.alpha_composite(shadow_layer, dest=(pos_x + 10, pos_y + 16))

    scene = Image.alpha_composite(scene, shadow)
    scene.alpha_composite(bong, dest=(pos_x, pos_y))
    scene.convert("RGB").save(out_path, "JPEG", quality=92)


def _input_for(model_alias: str, prompt: str, aspect_ratio: str) -> dict:
    """Build the input dict the chosen model expects. FLUX models accept
    aspect_ratio + output_format; SDXL needs width/height."""
    if model_alias == "nb":
        # nano-banana takes the prompt + a list of reference images and
        # places the reference subject into the scene at proper scale.
        # The reference URL is injected in generate_one_nb (we don't have
        # access to it here).
        return {
            "prompt": prompt,
            "image_input": [],   # filled in caller
            "output_format": "jpg",
            "aspect_ratio": aspect_ratio,
        }
    if model_alias in ("pro", "ultra", "dev", "schnell"):
        d = {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "output_format": "jpg",
            "output_quality": 92,
            "safety_tolerance": 5,
            # Lets the model's internal LLM rewrite the prompt for better
            # multi-element scene composition. Without this, complex
            # location-plus-subject prompts often collapse into a single
            # studio shot of the subject. Schnell doesn't support it.
            "prompt_upsampling": True,
        }
        if model_alias == "schnell":
            d.pop("safety_tolerance", None)
            d.pop("prompt_upsampling", None)
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


def _replicate_run_retry(model: str, inp: dict, max_attempts: int = 4):
    """replicate.run() with Replicate-rate-limit retry honoring the server's
    'in ~Xs' hint."""
    for attempt in range(1, max_attempts + 1):
        try:
            return replicate.run(model, input=inp)
        except Exception as e:
            msg = str(e)
            is_429 = "429" in msg or "throttled" in msg.lower() or "rate limit" in msg.lower()
            if not is_429 or attempt == max_attempts:
                raise
            wait = 12 * attempt
            import re
            m = re.search(r"in ~?(\d+)\s*s", msg)
            if m:
                wait = max(int(m.group(1)) + 2, 6)
            print(f"  ⟲ rate-limited (attempt {attempt}/{max_attempts}) — waiting {wait}s…")
            time.sleep(wait)
    raise RuntimeError("unreachable")


def generate_one(prompt: str, dest: Path, model_alias: str, aspect_ratio: str, dry: bool) -> str:
    """Text-to-image only (no composite). Used when --no-composite is passed."""
    if dry:
        return f"[DRY] would generate → {dest.name}\n        {prompt[:120]}…"
    model = MODELS[model_alias]
    inp = _input_for(model_alias, prompt, aspect_ratio)
    output = _replicate_run_retry(model, inp)
    n = _download(output, dest)
    return f"  ✓ {dest.name}  ({n // 1024} KB)"


def build_nb_prompt(scene_id: str, slot: str) -> str:
    """nano-banana prompt: describe the LOCATION + ACTION + how the
    purple bong from the reference image should be placed. Never names
    Jerome (avoids the model rendering a human character)."""
    nb_subject = (
        "The tall handblown purple glass bong from the reference image — "
        "translucent deep-purple beaker bong, decorative coil at the "
        "mouthpiece, dichroic glass marble cluster on the neck, golden "
        "downstem and bowl, round spherical purple beaker base. Place it "
        "standing upright at exactly 5 feet 6 inches tall (head-height for "
        "a typical adult standing next to him). Render the bong itself "
        "exactly as shown in the reference image, no alterations. Add a "
        "faint internal purple glow and a thin wisp of pale smoke from "
        "the top. Integrate him into the scene with proper shadow, "
        "perspective, and natural lighting that matches the location."
    )
    if scene_id == "hero":
        return (
            "Dramatic editorial photograph at street level on a busy "
            "Manhattan night. " + nb_subject + " Iconic blurred NYC night "
            "skyline behind him, light trails of moving cars. Cinematic "
            "35mm film grain, shallow depth of field. " + STYLE
        )
    s = SCENES[scene_id]
    # Strip "Jerome" from variant copy — otherwise nano-banana may render
    # an additional human "Jerome" alongside the bong (the bug that hit
    # 06-b: a guy in shorts appeared in the beach scene).
    variant_text = s['variants'][slot].replace("Jerome", "the bong").replace("him", "it")
    return f"{s['base']} {variant_text} {nb_subject} {STYLE}"


def generate_one_nb(scene_id: str, slot: str, dest: Path,
                     reference_url: str, aspect_ratio: str, dry: bool) -> str:
    """nano-banana pipeline: send Jerome reference + scene prompt to the
    model, get back a fully integrated scene in one call."""
    prompt = build_nb_prompt(scene_id, slot)
    if dry:
        return f"[DRY] nano-banana → {dest.name}\n        {prompt[:120]}…"
    output = _replicate_run_retry(
        MODELS["nb"],
        {
            "prompt": prompt,
            "image_input": [reference_url],
            "output_format": "jpg",
            "aspect_ratio": aspect_ratio,
        },
    )
    n = _download(output, dest)
    return f"  ✓ {dest.name}  ({n // 1024} KB)"


def generate_one_composite(scene_id: str, slot: str, dest: Path,
                            bong_png_bytes: bytes, model_alias: str,
                            aspect_ratio: str, dry: bool) -> str:
    """Composite pipeline: generate scene background (no Jerome), then PIL-
    paste the bg-removed bong PNG on top at the configured scale/position."""
    bg_prompt = build_bg_prompt(scene_id, slot)
    if dry:
        return f"[DRY] would generate bg + composite → {dest.name}\n        {bg_prompt[:120]}…"
    model = MODELS[model_alias]
    inp = _input_for(model_alias, bg_prompt, aspect_ratio)
    output = _replicate_run_retry(model, inp)
    bg_tmp = dest.with_suffix(".bg.jpg")
    _download(output, bg_tmp)
    cfg = get_composite_cfg(scene_id if scene_id != "hero" else "hero", slot or "a")
    composite_jerome(bg_tmp, bong_png_bytes, dest,
                     scale=cfg["scale"], x_pct=cfg["x_pct"],
                     y_pad_pct=cfg["y_pad_pct"])
    try:
        bg_tmp.unlink()
    except OSError:
        pass
    return f"  ✓ {dest.name}  ({dest.stat().st_size // 1024} KB)"


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
    p.add_argument("--model", default="nb", choices=list(MODELS.keys()),
                   help="Replicate model alias (default: nb = nano-banana, places reference at proper scale)")
    p.add_argument("--aspect", default="16:9", choices=["16:9", "4:3", "1:1"],
                   help="Aspect ratio (default 16:9 — matches hero + first slot)")
    p.add_argument("--no-composite", action="store_true",
                   help="Skip the PIL composite pipeline; render Jerome via text-to-image only.")
    p.add_argument("--parallel", type=int, default=1,
                   help="Concurrent predictions (default 1). Set to ~8 for fast batches.")
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

    # If nano-banana mode: upload Jerome reference once, share URL across calls.
    nb_reference_url: str | None = None
    bong_png_bytes: bytes | None = None
    if args.model == "nb" and not args.dry_run:
        ref_path = here.parent / "assets" / "jerome-reference.png"
        if not ref_path.exists():
            sys.exit(f"nano-banana needs {ref_path}")
        print(f"Uploading Jerome reference for nano-banana…")
        with open(ref_path, "rb") as f:
            obj = replicate.files.create(file=f)
        nb_reference_url = obj.urls["get"]
        print(f"  → {nb_reference_url}")
    elif not args.no_composite and not args.dry_run:
        transparent_path = here.parent / "assets" / "jerome-reference-transparent.png"
        if not transparent_path.exists():
            sys.exit(
                f"Composite mode requires {transparent_path}. "
                f"Pass --no-composite to fall back to text-to-image."
            )
        bong_png_bytes = transparent_path.read_bytes()
        print(f"Loaded transparent Jerome ({len(bong_png_bytes) // 1024} KB)")

    cost_per = COSTS.get(args.model, 0.04)
    total = len(plan) * cost_per
    if args.model == "nb":
        mode = "NANO-BANANA (reference-driven, native scale)"
    elif args.no_composite:
        mode = "TEXT-TO-IMAGE"
    else:
        mode = "COMPOSITE (scene bg + Jerome PNG paste)"

    print(f"Plan: {len(plan)} image(s) · model={MODELS[args.model]} · aspect={args.aspect}")
    print(f"Mode: {mode}")
    print(f"Estimated cost: ${total:.2f}  (${cost_per:.3f}/image)")
    print()

    def _one(args_tuple):
        sid, slot, dest = args_tuple
        label = "hero" if sid == "hero" else f"scene {sid} slot {slot}"
        try:
            if args.model == "nb":
                line = generate_one_nb(sid, slot, dest, nb_reference_url,
                                       args.aspect, args.dry_run)
            elif args.no_composite:
                prompt = build_prompt(sid, slot)
                line = generate_one(prompt, dest, args.model, args.aspect, args.dry_run)
            else:
                line = generate_one_composite(
                    sid, slot, dest, bong_png_bytes,
                    args.model, args.aspect, args.dry_run,
                )
            return f"  {label} → {dest.name}\n{line}"
        except Exception as e:
            return f"  ✗ {label} → {dest.name} FAILED: {e}"

    if args.parallel > 1 and not args.dry_run:
        # Concurrent predictions — Replicate accepts multiple in-flight,
        # bounded by account-wide rate limits (auto-retried).
        from concurrent.futures import ThreadPoolExecutor, as_completed
        print(f"Firing {len(plan)} prediction(s) with parallel={args.parallel}…")
        with ThreadPoolExecutor(max_workers=args.parallel) as ex:
            futs = {ex.submit(_one, t): t for t in plan}
            done = 0
            for fut in as_completed(futs):
                done += 1
                print(f"[{done}/{len(plan)}] {fut.result()}")
    else:
        for i, t in enumerate(plan, 1):
            print(f"[{i}/{len(plan)}] {_one(t)}")
            if not args.dry_run and i < len(plan):
                time.sleep(0.3)


if __name__ == "__main__":
    main()
