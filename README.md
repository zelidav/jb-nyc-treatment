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

Drop image files into the `img/` folder using the exact filenames in [img/README.md](img/README.md). Each scene supports up to 3 images (a/b/c). Missing slots show a styled placeholder card with the expected filename — there's no editing required to swap images in or out.

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
