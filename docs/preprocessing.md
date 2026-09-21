# Advanced photo preprocessing

Run all commands below from the repository root. See [development setup](development.md) first.

## Photo preprocessing GUI

From this folder, run:

```sh
.venv/bin/python tools/preprocess_gui.py
```

It opens a local-only browser interface at an available `127.0.0.1` port. Choose the
target at the top of the interface. These are preprocessing presets only: they identify
a native screen size and do not claim that Photo Frame has been physically tested on
that model.

| Target | Native portrait resolution | Default output folder |
| --- | ---: | --- |
| Kindle Basic (7th–10th generation) | 600 × 800 | `~/Kindle Photo Prep Exports/Kindle Basic older` |
| Kindle Basic (11th generation) | 1072 × 1448 | `~/Kindle Photo Prep Exports/Kindle Basic 11` |
| Kindle Paperwhite (1st / 2nd generation) | 758 × 1024 | `~/Kindle Photo Prep Exports/Paperwhite 1-2` |
| Kindle Paperwhite 3 (PW3) | 1072 × 1448 | `~/Kindle Photo Prep Exports/Paperwhite 3` |
| Kindle Paperwhite 4 (PW4) | 1072 × 1448 | `~/Kindle Photo Prep Exports/Paperwhite 4` |
| Kindle Voyage | 1072 × 1448 | `~/Kindle Photo Prep Exports/Voyage` |
| Kindle Oasis (1st generation) | 1072 × 1448 | `~/Kindle Photo Prep Exports/Oasis 1` |
| Kindle Paperwhite 5 (11th generation) | 1236 × 1648 | `~/Kindle Photo Prep Exports/Paperwhite 5` |
| Kindle Oasis 2 / 3 | 1264 × 1680 | `~/Kindle Photo Prep Exports/Oasis 2-3` |
| Kindle Scribe (1st generation) | 1860 × 2480 | `~/Kindle Photo Prep Exports/Scribe 1` |
| Other Kindle / Custom resolution | Entered by the user | `~/Kindle Photo Prep Exports/Custom Kindle` |

PW3 remains the default. Switching the target updates the preview and changes between
separate default output folders so files for different resolutions are not mixed. Use the
folder buttons to choose source and export folders. Custom width and height accept whole
pixel values from 1 through 10,000.

### Resolution sources

The names and generations were checked against [Amazon’s Kindle guide index](https://digprjsurvey.amazon.com/csad/help/node/G7N7RPHV2SW8CKBW)
and the [KOReader Kindle backend](https://github.com/koreader/koreader/blob/master/frontend/device/kindle/device.lua).
Native dimensions were cross-checked against the established [MobileRead screen-size reference](https://wiki.mobileread.com/wiki/Screen_size),
the [Kindle e-reader screensaver-size table](https://ebookscreensaver.com/screensaver-size),
and the [Kindle comparison table](https://www.the-ebook-reader.com/kindle-comparison.html)
where applicable. The older Basic, Paperwhite, and first Oasis groupings retain separate
user-facing names even when their panel dimensions are identical. The Scribe size is also
consistent with Amazon’s description of its 10.2-inch, 300-PPI display.

The default **Medium** preset uses the saved “mid contrast” recipe: 5% clipping,
sigmoid 5.4, gamma 1.7, linear contrast 0.85, sharpness 1.5, and JPEG output.
**Strong** uses “high contrast”: 6% clipping, sigmoid 6.3, gamma 2.15,
linear contrast 0.9, sharpness 1.5, and PNG output. Both use center crop,
white background, brightness 1, sigmoid midpoint 0.5, no dithering, 200 gray
levels, and JPEG quality 88 (only applicable to JPEG). Selecting either leaves
your Kindle model unchanged. **Gentle** keeps its original neutral controls
and 0.5% clipping. Explicit CLI controls override preset values.
Moving a tone slider switches the interface to **Custom**.

To keep a combination, enter a name under **Save current settings as** and
press **Save**. Named presets persist in the per-user `Kindle Photo Prep/presets.json` file and include
all tone, crop, format, quality, and dithering controls. They intentionally do
not store folder paths or the overwrite choice. Select a saved preset and press
**Load** to restore it, or **Delete** to remove it.

The open page checks the source folder every two seconds. Added, removed,
renamed, or replaced images appear automatically without a browser refresh. It
keeps the currently displayed photo selected when possible and reports folder
changes in the status line. Background polling pauses while the tab is hidden
and catches up as soon as it becomes visible again.

Useful controls:

- **Black/white clipping** expands the useful tonal range. It is usually the
  most effective fix for flat, gray-looking photos, but high values lose shadow
  and highlight detail.
- **Sigmoid contrast** strengthens separation around the midpoint while keeping
  the extremes smoother than simple linear contrast.
- **Gamma** adjusts midtones. Values above 1 brighten them; values below 1
  darken them.
- **Brightness** shifts the whole image; **linear contrast** expands or
  compresses values around the average; **sharpness** boosts local edges.
- **Sigmoid midpoint** moves the contrast transition. Below 0.5 favors darker
  tones; above 0.5 favors lighter tones.
- **Dithering / gray levels** deliberately quantizes grayscale. Leave it off
  initially because KOReader's display path may already dither effectively. If
  enabled, use PNG so JPEG artifacts do not damage the pattern.

Each export writes `manifest.tsv` and `processing-settings.json` alongside the
images. The latter records the target device, native size, and exact controls
used for that batch. Named GUI presets also remember their target device.

The command-line tool exposes the same controls. For example:

```sh
.venv/bin/python tools/preprocess_images.py "test images" prepared-photos \
  --device pw3 --preset medium --overwrite
```

For a first-generation Scribe:

```sh
.venv/bin/python tools/preprocess_images.py "test images" \
  prepared-photos-scribe --device scribe1 --preset medium --overwrite
```

The custom-resolution option is currently a GUI feature; the command-line tool uses
`--size WIDTHxHEIGHT` for a one-off target.

Pillow is used rather than FFmpeg because this is a still-image pipeline and
Pillow gives direct, lightweight access to all required tone and preview
operations. Processing remains on the computer, not the Kindle.

`tools/requirements.txt` also installs `pillow-heif`, allowing genuine
HEIC/HEIF photos to use the same first-frame, EXIF-orientation, crop, and tone
pipeline as JPEG photos. Re-run the requirements command after pulling changes:

```sh
.venv/bin/python -m pip install -r tools/requirements.txt
```

Every batch overwrites `failures.tsv` in the output folder. The report contains
one row per failed source and does not grow indefinitely. A successful batch
leaves only its header, making stale failures unambiguous.
