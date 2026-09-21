# Workspace 2 demo

Real desktop footage: Gmail on the front, WhatsApp and Telegram sharing the
back. The clip shows flipping, temporarily unfolding all three apps, folding
back and returning to Gmail. It uses the experimental hy3 container build.

- [Video](hyprflip-demo.mp4): silent 1920×1080, 60 fps H.264.
- [Looping preview](hyprflip-preview.gif): 1000×562, 25 fps GIF.
- [Poster](hyprflip-poster.png): still showing the unfolded card.
- [Capture details](capture-info.json): export settings and editing details.

The app contents are shown as captured. The entire desktop frame is resized to
fit the presentation, with captions placed outside it. Motion comes from the
actual compositor recording at its original speed. The captions are aligned to
the visible transitions, and the last frame is held for 1.3 seconds to give the
loop a pause.

Only the public exports belong in Git. Raw captures and desktop state are kept
out of the repository history.

## Recording this desktop

This take uses `wf-recorder` 0.6.0 with software `libx264` encoding and
`--no-dmabuf`. The card's membership, pane order, split sizes, remembered focus,
visible face and folded state were checked after capture and restored.

For a manual recording, choose the intended monitor and an existing private
output directory, then stop with Ctrl+C:

```sh
wf-recorder --no-dmabuf -D -c libx264 \
  -p preset=ultrafast -p crf=16 -p threads=4 \
  -x yuv420p -r 60 -F scale=1920:1080 \
  -o YOUR_MONITOR -f /path/to/private-directory/workspace.mkv
```

The files linked above add a trim and caption pass to the original recording.
Keep source footage outside Git, and use a persistent directory rather than
`/tmp` so a reboot does not erase the take.

Recorder options are documented in the
[wf-recorder manual](https://github.com/ammen99/wf-recorder/blob/master/manpage/wf-recorder.1).
