# Kindle photo-frame design and experiment plan

## Scope

- Kindle Paperwhite 3 / “PW3” (1072 × 1448 pixels).
- Kindle Scribe, first generation (1860 × 2480 pixels).
- KOReader stays running and the Kindle stays in airplane mode.
- Photos are local, pre-oriented, pre-cropped, exact-size grayscale files.
- The device sleeps between 15-minute changes.

## KOReader APIs inspected

The implementation was developed against KOReader commit
`03fe3be9adaabebaef85f0c13094414662fde600` dated 2026-08-21.

- `frontend/device/wakeupmgr.lua`: task queue, callback identity, alarm
  promotion after a callback.
- `frontend/device/kindle/powerd.lua`: LIPC-backed mock RTC, the
  `ReadyToSuspend` constraint, 15-second unexpected-wake filter, and 90-second
  alarm proximity window.
- `frontend/device/kindle/device.lua`: Kindle sleep-screen entry/exit and
  `WakeupFromSuspend`/`ReadyToSuspend` event handling.
- `frontend/ui/screensaver.lua` and `ui/widget/screensaverwidget.lua`: supported
  image widget, full refresh, close, rotation, and cleanup behavior.
- `frontend/ui/widget/imagewidget.lua`: image decoding through KOReader's
  rendering abstraction with `file_do_cache = false`.
- `frontend/ui/uimanager.lua`: full repaint, vsync wait, and normal suspend
  request.
- `plugins/autosuspend.koplugin/main.lua`: established `WakeupMgr` task
  ownership and suspend/resume cleanup patterns.

## Lifecycle

1. User enables the plugin and requests sleep.
2. Kindle creates its ordinary KOReader sleep screen and broadcasts `Suspend`.
3. The plugin selects and persists the next shuffled image, replaces the sleep
   screen with a full-screen image widget, waits for the refresh, and queues a
   900-second `WakeupMgr` task.
4. During Kindle's internal RTC maintenance wake, KOReader validates the alarm
   and invokes the callback while powerd still reports `screenSaver` or
   `suspended`.
5. The callback swaps the image inside the same top-level sleep-screen widget,
   performs one full refresh, queues the next task, and returns. Kindle powerd
   handles re-suspend.
6. A button/cover user wake produces a normal `Resume`; the plugin removes the
   pending maintenance task until the next suspend.

Direct framebuffer access and direct LIPC/sysfs calls are intentionally absent.

## Image format decision

Start with baseline, non-progressive grayscale JPEG at the selected device's
native portrait resolution and quality 88. This avoids runtime
orientation/cropping/scaling and keeps storage reads small while leaving
KOReader's well-tested decoder path intact. JPEG decoding is expected to be a
much smaller cost than radio use or remaining awake.

```sh
# Paperwhite 3
python3 tools/preprocess_images.py source prepared-pw3 --device pw3

# First-generation Scribe
python3 tools/preprocess_images.py source prepared-scribe --device scribe1
```

The preprocessor can instead make a 16-level Floyd–Steinberg PNG:

```sh
python3 tools/preprocess_images.py source prepared-png \
  --format png --dither floyd-steinberg --levels 16
```

Use that only as an A/B test. PNG files may be larger and pre-dithering is not
automatically more energy-efficient.

## Acceptance tests

### Bench test (plugged in)

1. Install the plugin and 3–5 visibly numbered, device-profiled test images.
2. Select **Change photo every**, enter `2`, and start the frame.
3. Confirm at least three rotations without touching the Kindle.
4. Confirm each image fills the screen, is upright, and gets a clean full
   refresh.
5. Wake with the power button. Confirm KOReader becomes usable and no additional
   RTC rotation occurs while actively using it.
6. Inspect `photo_frame.tsv`: every maintenance cycle should have `wake`,
   `rendered`, `wake_scheduled`, and `return_to_suspend`, with no
   `render_error`.
7. Confirm output dimensions are 1072 × 1448 on PW3 or 1860 × 2480 on Scribe.
8. Disable diagnostic TSV logging and restore the interval to `15` minutes
   before the battery test.

### Restart/state test

1. Use numbered images and note `last_image` and `playlist_index` in the state
   file.
2. Restart KOReader, suspend again, and verify the shuffle continues instead of
   restarting at its first entry.
3. Remove one queued image and verify it is skipped rather than crashing.

### Overnight battery comparison

Run each condition for at least three nights, beginning near the same charge,
room temperature, frontlight level, and duration. Disconnect USB before the
start reading and do not interact with the device during a run.

1. Baseline: airplane mode, KOReader suspended, plugin disabled.
2. Treatment: airplane mode, plugin enabled, 900-second JPEG rotation.
3. Optional format A/B: same treatment with pre-dithered PNG.

Record start/end timestamps and battery percentages plus the count of
`rendered` events. Compare percentage points per hour, not only raw overnight
loss. Treat a missing sequence, unexpected user resume, charging event, or
large duration mismatch as an invalid run. Battery percentage is coarse, so
prefer repeated long runs over conclusions from a single night.

## Known risk

The current source implements the intended Kindle maintenance-wake path, but it
cannot prove behavior on a specific model, firmware, and KOReader binary
without a device run. Run the narrow bench test separately on PW3 and Scribe;
success on one model is not evidence that the other model's powerd timing is
identical.
