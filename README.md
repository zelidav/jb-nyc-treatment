# Jerome Baker Comes to New York — Campaign Treatment

Interactive single-page GH Pages site for the JBNY viral campaign treatment. Sticky scene nav on the left, 13 scene cards with image slots, execution notes, posting sequence, and captions. Cinematic dark theme with Jerome's purple as the accent.

## Local preview

Open `index.html` directly in a browser — no build step.

Or run a quick local server (preferred for the IntersectionObserver to behave):

```bash
python -m http.server 8000
# → http://localhost:8000
```

## Adding images

Three options:

**1. Drop your own** — place files in `img/` using the filenames in [img/README.md](img/README.md). Each scene supports up to 3 images (a/b/c). Missing slots show a styled placeholder card with the expected filename — no code edits needed.

**2. Generate with Replicate (FLUX)** — every scene has a hand-tuned prompt in `tools/generate.py`. Set your Replicate token and batch-generate every missing slot:

```bash
pip install -r requirements.txt
# bash / zsh:
export REPLICATE_API_TOKEN=r8_...
# PowerShell (session-only):
$env:REPLICATE_API_TOKEN = "r8_..."

python tools/generate.py                       # all missing slots (~$1.60 batch on flux-1.1-pro)
python tools/generate.py --scene 03            # just scene 03
python tools/generate.py --slot a              # only the "a" of each scene
python tools/generate.py --model schnell       # fast + cheap iteration (~$0.003/image)
python tools/generate.py --model ultra         # flux-1.1-pro-ultra (~$0.060/image)
python tools/generate.py --aspect 4:3          # change aspect ratio
python tools/generate.py --hero                # also regenerate hero.jpg
python tools/generate.py --hero-only           # just the hero
python tools/generate.py --dry-run             # preview the plan, no API calls
python tools/generate.py --force --scene 04    # overwrite all 3 slots of scene 04
```

The script is idempotent: it skips slots that already exist (pass `--force` to overwrite). Every prompt prepends a consistent Jerome character description so the bong looks recognizably the same across scenes.

Model aliases: `pro` (default · flux-1.1-pro), `ultra` (flux-1.1-pro-ultra), `dev` (flux-dev), `schnell` (flux-schnell), `sdxl`.

**3. Trigger Replicate from GitHub Actions** — keeps the API key off your laptop. Go to the repo's **Actions** tab → **Generate images** workflow → **Run workflow**, pick model/scene/slot/etc., hit Run. The workflow reads `REPLICATE_API_TOKEN` from repo secrets, runs `tools/generate.py`, and commits any new images back to `master`. GH Pages rebuilds in ~30s. See [Setup](#setup) below.

**4. Mix the above** — generate placeholders first, then swap real photos in as you shoot them. Filenames match either way.

## Setup

To use the Actions workflow (option 3 above), add your Replicate token as a repo secret — once. Two ways:

**Via GitHub UI:** Settings → Secrets and variables → Actions → **New repository secret**. Name: `REPLICATE_API_TOKEN`. Value: your `r8_...` token.

**Via gh CLI** (never appears in shell history or chat):

```bash
gh secret set REPLICATE_API_TOKEN -R zelidav/jb-nyc-treatment
# (paste value when prompted, hit Enter)
```

After that, just run the workflow from the Actions tab whenever you want new images.

## Deploying to GitHub Pages

```bash
git init
git add .
git commit -m "Initial — JB NYC campaign treatment"
git branch -M main
git remote add origin git@github.com:<you>/jb-nyc-treatment.git
git push -u origin main
```

Then in the repo settings → Pages → Build from branch `main` / root. Site goes live at `https://<you>.github.io/jb-nyc-treatment/` in ~1 min.

For a private staging URL while images are still being added, mark the repo private and use a [GH Pages Pro / Vercel / Netlify] deploy with auth — or keep public but unindexed via the `<meta name="robots" content="noindex,nofollow">` already in `index.html`.

## File map

```
jb-nyc-treatment/
├── index.html       ← all content, single page
├── styles.css       ← cinematic dark theme + purple/red/yellow accents
├── script.js        ← scene nav active-state, lightbox, mobile drawer
├── README.md        ← this file
└── img/
    ├── README.md    ← exact filenames to drop in
    └── (drop images here)
```

## Tone / brand notes

- Jerome is `he` everywhere — never "it" or "the piece"
- Purple is Jerome's color — the page's primary accent
- Red is reserved for the Federal Building / Authority Confrontation moments
- Yellow is for emphasis (drop quotes, on-screen text callouts)
- `Confidential — Internal Use Only` ribbon is intentional and persists
