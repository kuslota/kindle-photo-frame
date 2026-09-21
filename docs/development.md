# Development and releases

The [beginner guide](../README.md) uses release packages and needs no development tools.
The Lua plugin and the Python/Pillow pipeline remain separate. The browser talks only
to an HTTP server bound to `127.0.0.1`; it loads no remote resources. Host and Origin
checks reject foreign web pages. No analytics or network photo processing are used.

## Run from source

Use Python 3.12 with Tcl/Tk (the standard python.org Windows/macOS distributions
include it). Linux needs its distribution's Tk package and a graphical desktop for
the folder picker. A Python build without Tk can still run the CLI or headless server.
From the repository root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r tools/requirements.txt
.venv/bin/python tools/preprocess_gui.py
```

On Windows use `.venv\Scripts\python.exe` instead of `.venv/bin/python`.
Source mode also opens a browser and uses the same folder picker. CLI options
`--input`, `--output`, `--device`, `--port`, `--presets` and `--no-browser` remain
available. Port defaults to 0 (OS-selected, avoiding a probe/bind race). Headless
mode prints the chosen address and stops with Control-C or `/api/quit`.
In normal mode, use **Quit Photo Prep**. Closing a browser tab does not stop the
server; each launch has its own port and Quit ends only that instance.

```sh
.venv/bin/python tools/preprocess_images.py source-photos prepared-photos --device pw3 --preset medium
.venv/bin/python tools/preprocess_images.py source-photos prepared-scribe --device scribe1 --preset medium
.venv/bin/python -m unittest discover -s tests
```

See [preprocessing controls](preprocessing.md), [plugin internals and logging](../photo_frame.koplugin/README.md),
and [Kindle bench tests](../notes/design.md). Input images and user presets stay ignored.

## Resources and writable data

`tools/app_paths.py` centralizes locations. Resources are relative to the module's
`__file__`, which PyInstaller also supplies inside the bundle. The spec places HTML
there; processing modules are collected as Python imports.
See [PyInstaller's runtime path documentation](https://www.pyinstaller.org/en/stable/runtime-information.html).

Saved presets go to:

| Platform | Directory |
| --- | --- |
| Windows | `%LOCALAPPDATA%\Kindle Photo Prep\presets.json` |
| macOS | `~/Library/Application Support/Kindle Photo Prep/presets.json` |
| Linux | `$XDG_DATA_HOME/Kindle Photo Prep/presets.json` (default `~/.local/share`) |

Use `--presets .photo-frame-presets.json` to keep using a legacy repository-local
preset file, or copy it to the new location while the app is stopped. No automatic
migration writes into the source checkout or installed bundle. Default exports go
under `~/Kindle Photo Prep Exports`, separated by device. Source/output overlap is
rejected and overwrite defaults to off. Processing math is unchanged.

## Native release builds

GitHub Actions **Build release packages** supports **Run workflow** and `v*` tags.
It builds Windows x64 on Windows and Apple Silicon on macOS, with Python 3.12.
No Intel/universal or Linux binary is claimed. Manual runs provide downloadable
workflow artifacts (GitHub wraps each distributable ZIP in an artifact download).
Tag runs attach the three named ZIPs to a draft GitHub Release; review the assets,
complete the checks below, and publish the draft. Only existing drafts receive updated
assets; published releases are never overwritten. No binaries or generated build directories belong in Git.

To build locally on the target platform:

```sh
python -m pip install -r packaging/requirements-build.txt
python -m PyInstaller --clean --noconfirm packaging/KindlePhotoPrep.spec
python tools/smoke_packaged.py
python tools/package_plugin.py
```

The spec uses one-folder mode, includes HTML, Pillow, pillow-heif and native
libraries, and lets PyInstaller collect Tcl/Tk. Windows uses a windowed `.exe`;
macOS uses an `.app`. Only folder dialogs use Tk; the interface remains in the
browser. Tk dialogs run on the main thread, with the server on a background thread.
On macOS archive using `ditto` as in the workflow to preserve bundle symlinks.

Initial packages have no Windows publisher signature or Apple Developer ID /
notarization. PyInstaller may apply an ad-hoc macOS signature needed to run on
Apple Silicon; this does not establish developer trust. To add signing later,
configure the spec's signing identity and entitlements, sign on the native runner,
then notarize/staple the app before archiving. Keep credentials in release secrets.
No security settings or quarantine attributes are altered by this project.

## Release verification checklist

Automated checks cover processing regression, resource/data paths, plugin ZIP
layout, HTTP protections and a frozen smoke test (HTML, Tcl/Tk, HEIF decode and
photo export). These do not prove browser/OS dialogs or physical Kindle sleep behavior.

Before publishing each release:

- [ ] On clean Windows x64 without Python, extract the ZIP, double-click the EXE,
  handle the expected SmartScreen prompt, and confirm no console remains open.
- [ ] On Apple Silicon without developer tools, extract/open the app, check the
  documented Gatekeeper prompt and automatic browser launch.
- [ ] On both, choose/cancel/reopen source and export dialogs, including spaces,
  non-ASCII names and a read-only destination (must report an error).
- [ ] Preview JPEG, PNG and HEIC; export every built-in device profile. Confirm dimensions,
  saved presets across relaunches, default no-overwrite, completion and Quit.
- [ ] Move the extracted app to another folder and repeat; bundle must stay intact.
- [ ] Confirm two simultaneous launches use different ports. Check browser fallback.
- [ ] USB-copy the plugin ZIP contents and exports; verify the two-minute sleep
  photo cycling and normal interval on PW3 and Scribe separately. Record KOReader/firmware.
- [ ] Check that documentation images reflect the release and contain no private metadata.

No jailbreak or automatic USB installation is included.

See the [first release guide](releasing.md) for publication steps.
