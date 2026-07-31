# HookLens — Build Spec

You are building a demo web app for a 5-day solo hackathon (PrincetonBuilds Ideathon, presenting Sunday 8PM). Read this entire file before writing any code.

**What it is:** upload a short-form video → get a frame-by-frame prediction of where human visual attention goes → get an actionable diagnosis of why the video does or doesn't hold attention.

**Framing matters more than the model here.** This is NOT "we made a heatmap." It is **a diagnostic tool that tells creators why their first three seconds fail.** Every design decision should serve that framing. A heatmap is impressive for five seconds; a verdict like *"your text overlay sits in a dead zone — 71% of predicted attention never reaches it"* is a product.

---

## HARD CONSTRAINTS

1. **CPU only.** Saliency models are 20–100MB and run in tens of ms/frame. Never write code requiring a GPU. If something needs a GPU, it's the wrong approach.
2. **Ship the boring version first.** Per-frame image saliency with a maintained model, working end to end, before any temporal model is attempted.
3. **The analysis layer is the product.** The saliency model is a commodity — every hour spent there is wasted. Spend time on metrics and verdicts.
4. **Phase order is not optional.** Do not start Phase N+1 until Phase N's acceptance criteria pass.
5. Solo dev, 5 days. Flat files, single app, no database, no auth.

---

## Model strategy

**Start here (Phase 1):** per-frame image saliency using a maintained HF model — `alexanderkroner/saliency` (working HF Space, hosted weights). Guaranteed to run, no bitrot risk. Loses temporal smoothing; acceptable.

**Optional upgrade (only if Phases 1–3 are done):** [UNISAL](https://github.com/rdroste/unisal) for true video saliency with temporal coherence. Pretrained weights ship in `training_runs/pretrained_unisal`. **Warning:** ECCV 2020 code, five-year-old PyTorch, likely dependency conflicts. Timebox any attempt to 2 hours; abandon on failure. Per-frame results are fine for the demo.

**Cheap temporal smoothing without a video model:** exponential moving average across per-frame saliency maps (α ≈ 0.6). Gets you most of the visual benefit of a temporal model for four lines of code. Do this instead of UNISAL if short on time.

---

## Known limitations — handle explicitly, disclose in the app

- **Center bias.** Saliency models trained on SALICON/MIT1003 have strong learned center bias. Compute and report a center-bias-corrected variant alongside raw output, or at minimum disclose it. A judge who knows CV will raise this.
- **Vertical video is out of distribution.** Training data is mostly landscape natural images; 9:16 short-form is not. Pad rather than squash when resizing (squashing distorts spatial relationships and corrupts predictions). Note this as a limitation.
- **Predicted, not measured.** These are model predictions of aggregate human gaze, not eye-tracking of any individual. Say so plainly before anyone asks.

---

## Repo structure

```
hooklens/
├── CLAUDE.md
├── pipeline/
│   ├── saliency.py     # video → per-frame saliency maps
│   ├── metrics.py      # saliency maps → diagnostic scores   ← THE PRODUCT
│   ├── overlay.py      # saliency + frames → heatmap mp4
│   └── ocr.py          # locate text overlays (Phase 3)
├── data/
│   ├── videos/
│   ├── cache/          # .npy saliency arrays (gitignored)
│   └── results/        # <video_id>.json + heatmap mp4s
├── app/
│   └── app.py          # Gradio
└── requirements.txt
```

---

## PHASE 1 — Saliency pipeline

**Goal:** video in, heatmap-overlaid video out.

Steps: decode with ffmpeg → subsample to **5fps** (30fps is wasteful; attention doesn't change that fast) → run saliency per frame → EMA smooth → colormap → alpha-blend over original frames → re-encode to mp4.

**Acceptance:** `python pipeline/saliency.py --video data/videos/test.mp4` produces a heatmap mp4 in under 30 seconds on CPU for a 30-second clip.

---

## PHASE 2 — The metrics layer (this is the actual product)

Each metric must map to a **verdict a creator can act on**. A number alone is not a deliverable.

| Metric | Computation | Verdict it produces |
|---|---|---|
| **Hook strength** | Mean saliency concentration, first 3s | "Your opening has no clear focal point" |
| **Focus / clutter** | Spatial entropy of saliency map, per frame | "Three elements compete for attention at 0:02" |
| **Attention stability** | Frame-to-frame displacement of peak saliency | "Attention jumps 6× in the first 5s — viewers can't settle" |
| **Drift** | Slope of concentration over the clip | "Attention diffuses after 0:08 — you're losing them" |
| **Dead zones** | Regions with persistently low saliency | (feeds the text-placement check below) |
| **UI occlusion** | Overlap of high-saliency regions with platform UI mask | "22% of predicted attention lands under the caption bar" |

**UI occlusion is the highest-value metric and the best demo moment.** Platform chrome — captions, username, action buttons, progress bar — covers roughly the bottom 20% and right 15% of a Reel/TikTok. Hardcode an approximate mask. Showing a creator that their key visual is buried under the UI is immediately, viscerally useful.

**Output schema** — `data/results/<video_id>.json`, freeze this early:

```json
{
  "video_id": "abc123",
  "duration_sec": 28.5,
  "fps_sampled": 5,
  "timeline": [
    { "t": 0.0, "concentration": 0.72, "entropy": 2.1, "peak_xy": [0.51, 0.33], "ui_overlap": 0.04 }
  ],
  "scores": {
    "hook_strength": 0.68,
    "stability": 0.44,
    "drift_slope": -0.02,
    "ui_occlusion_pct": 0.22
  },
  "verdicts": [
    { "severity": "high", "t": 2.1, "text": "Text overlay sits in a low-attention region" }
  ],
  "heatmap_video": "abc123_heat.mp4"
}
```

**Acceptance:** a JSON with at least three populated verdicts on a real Reel.

---

## PHASE 3 — Web app

**Gradio**, deployed to HF Spaces (free CPU tier is sufficient — no ZeroGPU needed).

Layout:

```
┌──────────────────┬──────────────────┐
│  original video  │  heatmap overlay │
│                  │  (synced)        │
├──────────────────┴──────────────────┤
│  attention timeline w/ playhead      │
│  (concentration + UI-overlap traces) │
├──────────────────────────────────────┤
│  VERDICTS — plain English, severity   │
│  ranked, each timestamp clickable     │
└──────────────────────────────────────┘
```

Requirements:
- Both videos play from **one shared control**. Desync destroys the effect.
- Clicking a verdict seeks both videos to that timestamp. This is the interaction that makes it feel like a real tool.
- Ship a **precomputed gallery** of 6–8 analyzed Reels, including one obvious good/bad pair.
- **Live upload works here** (unlike a GPU project) — CPU inference is fast enough. Still cache results and keep the gallery as the fallback path if an upload fails on stage.

**Text overlay detection (do last):** OCR with `easyocr` to find text bounding boxes, then check them against the saliency map. This produces the single best verdict in the product — "your text is in a dead zone" — so build it if there's any time at all.

**Acceptance:** app runs, gallery navigates, videos stay synced, verdicts are clickable, works with wifi disabled.

---

## PHASE 4 — Validation (optional, only if ahead of schedule)

Collect ~40 Shorts with `yt-dlp` (`--dump-json` gives view/like counts) and test whether the metrics correlate with engagement.

- Target: `log(likes / views)` — **never raw views**, which mostly measures channel size
- Even a weak correlation is presentable; report holdout performance honestly
- If null: the tool still stands as a diagnostic. Do not let this phase block anything

---

## PHASE 5 — Sunday hardening

- Record a full screen capture of the demo working. Non-negotiable.
- Verify it runs with wifi off.
- Add a limitations panel: predicted not measured, center bias, vertical video is out of distribution.
- Freeze code. Broken things get cut, not fixed.

---

## Do NOT

- Do not train or fine-tune anything. Inference only.
- Do not require a GPU anywhere in the stack.
- Do not spend more than 2 hours on UNISAL. EMA smoothing over per-frame results is the fallback and it is fine.
- Do not squash vertical video to square when resizing — pad it.
- Do not present raw heatmaps without verdicts. The verdicts are the product.
- Do not use raw view counts as a target in Phase 4.
- Do not build auth, accounts, or a database.

---

## Suggested first message to Claude Code

> Read CLAUDE.md. Do Phase 1 only: scaffold the repo, write `pipeline/saliency.py` using the maintained HF image-saliency model, 5fps subsampling, EMA temporal smoothing, and heatmap mp4 output. Confirm it runs on CPU in under 30s for a 30-second clip. Do not write the app or metrics yet.
