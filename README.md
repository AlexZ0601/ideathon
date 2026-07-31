# HookLens

Upload a short-form video → get a frame-by-frame prediction of where human visual attention goes → get an actionable diagnosis of why the video does or doesn't hold attention.

Not just a heatmap: HookLens turns CPU-only saliency predictions into plain-English verdicts a creator can act on — *"your text overlay sits in a dead zone — 71% of predicted attention never reaches it."*

Built solo in 5 days for the PrincetonBuilds Ideathon.

## How it works

1. **Saliency pipeline** (`pipeline/saliency.py`) — decode video with ffmpeg, subsample to 5fps, run per-frame image saliency on CPU, smooth with an exponential moving average, render a heatmap-overlaid mp4.
2. **Metrics layer** (`pipeline/metrics.py`) — the actual product. Computes hook strength, focus/clutter, attention stability, drift, dead zones, and overlap with platform UI chrome, then emits severity-ranked verdicts (see `data/results/example.json` for the output schema).
3. **Web app** (`app/`) — Gradio UI with synced original/heatmap playback, an attention timeline, and clickable verdicts.

## Limitations

- Predictions of aggregate human gaze, not eye-tracking of any individual.
- Saliency models carry a learned center bias from their training data.
- Vertical 9:16 video is out of distribution for these models; frames are padded, not squashed, to mitigate.

## Structure

```
pipeline/   saliency, metrics, overlay, OCR
data/       videos (gitignored), cache (gitignored), results
app/        Gradio app
```
