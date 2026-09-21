#!/usr/bin/env python3
"""Prepare local photos for supported Kindle displays."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from pathlib import Path

try:
    from PIL import Image, ImageEnhance, ImageOps, UnidentifiedImageError
except ImportError as exc:  # pragma: no cover - exercised by installation, not tests
    raise SystemExit(
        "Pillow is required. Install it with: python3 -m pip install -r tools/requirements.txt"
    ) from exc

try:
    from pillow_heif import register_heif_opener
except ImportError:  # JPEG/PNG remain usable, with a focused HEIC error later.
    HEIF_SUPPORT = False
else:
    register_heif_opener()
    HEIF_SUPPORT = True


DEVICE_PROFILES = {
    "basic_older": {
        "label": "Kindle Basic (7th–10th generation)",
        "size": (600, 800),
    },
    "basic_11": {
        "label": "Kindle Basic (11th generation)",
        "size": (1072, 1448),
    },
    "pw1_2": {
        "label": "Kindle Paperwhite (1st / 2nd generation)",
        "size": (758, 1024),
    },
    "pw3": {
        "label": "Kindle Paperwhite 3 (PW3)",
        "size": (1072, 1448),
    },
    "pw4": {
        "label": "Kindle Paperwhite 4 (PW4)",
        "size": (1072, 1448),
    },
    "voyage": {
        "label": "Kindle Voyage",
        "size": (1072, 1448),
    },
    "oasis1": {
        "label": "Kindle Oasis (1st generation)",
        "size": (1072, 1448),
    },
    "pw5": {
        "label": "Kindle Paperwhite 5 (11th generation)",
        "size": (1236, 1648),
    },
    "oasis2_3": {
        "label": "Kindle Oasis 2 / 3",
        "size": (1264, 1680),
    },
    "scribe1": {
        "label": "Kindle Scribe (1st generation)",
        "size": (1860, 2480),
    },
}
PW3_SIZE = DEVICE_PROFILES["pw3"]["size"]
# Complete built-in recipes shared with the browser; device selection is independent.
TONE_PRESETS = {'none': {'fit': 'cover',
          'background': 255,
          'autocontrast_cutoff': 0.0,
          'sigmoid': 0.0,
          'sigmoid_midpoint': 0.5,
          'gamma': 1.0,
          'brightness': 1.0,
          'contrast': 1.0,
          'sharpness': 1.0,
          'dither': 'none',
          'levels': 16,
          'output_format': 'jpeg',
          'jpeg_quality': 88},
 'gentle': {'fit': 'cover',
            'background': 255,
            'autocontrast_cutoff': 0.5,
            'sigmoid': 0.0,
            'sigmoid_midpoint': 0.5,
            'gamma': 1.0,
            'brightness': 1.0,
            'contrast': 1.0,
            'sharpness': 1.0,
            'dither': 'none',
            'levels': 16,
            'output_format': 'jpeg',
            'jpeg_quality': 88},
 'medium': {'fit': 'cover',
            'background': 255,
            'autocontrast_cutoff': 5.0,
            'sigmoid': 5.4,
            'sigmoid_midpoint': 0.5,
            'gamma': 1.7,
            'brightness': 1.0,
            'contrast': 0.85,
            'sharpness': 1.5,
            'dither': 'none',
            'levels': 200,
            'output_format': 'jpeg',
            'jpeg_quality': 88},
 'strong': {'fit': 'cover',
            'background': 255,
            'autocontrast_cutoff': 6.0,
            'sigmoid': 6.3,
            'sigmoid_midpoint': 0.5,
            'gamma': 2.15,
            'brightness': 1.0,
            'contrast': 0.9,
            'sharpness': 1.5,
            'dither': 'none',
            'levels': 200,
            'output_format': 'png',
            'jpeg_quality': 88}}
SUPPORTED_SUFFIXES = {
    ".avif",
    ".bmp",
    ".gif",
    ".heic",
    ".heif",
    ".jpeg",
    ".jpg",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
}


def parse_size(value: str) -> tuple[int, int]:
    try:
        width, height = (int(part) for part in value.lower().split("x", 1))
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("size must look like WIDTHxHEIGHT") from exc
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError("width and height must be positive")
    return width, height


def grayscale_palette(levels: int) -> Image.Image:
    """Build a Pillow palette containing evenly spaced neutral grays."""
    palette = Image.new("P", (1, 1))
    values = [round(index * 255 / (levels - 1)) for index in range(levels)]
    entries: list[int] = []
    for value in values:
        entries.extend((value, value, value))
    entries.extend((255, 255, 255) * (256 - levels))
    palette.putpalette(entries)
    return palette


def apply_dither(image: Image.Image, mode: str, levels: int) -> Image.Image:
    if mode == "none":
        return image
    palette = grayscale_palette(levels)
    dithered = image.quantize(
        palette=palette,
        dither=Image.Dither.FLOYDSTEINBERG,
    )
    return dithered.convert("L")


def resolve_tone_settings(
    preset: str,
    autocontrast_cutoff: float | None,
    sigmoid: float | None,
) -> tuple[float, float]:
    values = TONE_PRESETS[preset]
    return (
        values["autocontrast_cutoff"] if autocontrast_cutoff is None else autocontrast_cutoff,
        values["sigmoid"] if sigmoid is None else sigmoid,
    )


def apply_tone(
    image: Image.Image,
    *,
    autocontrast_cutoff: float = 0.0,
    sigmoid: float = 0.0,
    sigmoid_midpoint: float = 0.5,
    gamma: float = 1.0,
    brightness: float = 1.0,
    contrast: float = 1.0,
    sharpness: float = 1.0,
) -> Image.Image:
    """Apply reproducible grayscale tone controls to an L-mode image."""
    if not 0 <= autocontrast_cutoff < 50:
        raise ValueError("autocontrast cutoff must be at least 0 and below 50")
    if sigmoid < 0:
        raise ValueError("sigmoid contrast must be at least 0")
    if not 0 < sigmoid_midpoint < 1:
        raise ValueError("sigmoid midpoint must be between 0 and 1")
    if min(gamma, brightness, contrast, sharpness) <= 0:
        raise ValueError("gamma, brightness, contrast, and sharpness must be positive")

    result = image.convert("L")
    if autocontrast_cutoff:
        result = ImageOps.autocontrast(
            result,
            cutoff=(autocontrast_cutoff, autocontrast_cutoff),
        )
    if sigmoid:
        low = 1.0 / (1.0 + math.exp(sigmoid * sigmoid_midpoint))
        high = 1.0 / (1.0 + math.exp(-sigmoid * (1.0 - sigmoid_midpoint)))
        scale = high - low
        lut = []
        for value in range(256):
            normalized = value / 255.0
            curved = 1.0 / (1.0 + math.exp(-sigmoid * (normalized - sigmoid_midpoint)))
            lut.append(round(255 * (curved - low) / scale))
        result = result.point(lut)
    if gamma != 1.0:
        # Conventional display gamma: values above 1 brighten midtones.
        result = result.point(
            [round(255 * ((value / 255.0) ** (1.0 / gamma))) for value in range(256)]
        )
    if brightness != 1.0:
        result = ImageEnhance.Brightness(result).enhance(brightness)
    if contrast != 1.0:
        result = ImageEnhance.Contrast(result).enhance(contrast)
    if sharpness != 1.0:
        result = ImageEnhance.Sharpness(result).enhance(sharpness)
    return result


def fit_image(
    image: Image.Image,
    size: tuple[int, int],
    fit: str,
    background: int,
) -> Image.Image:
    if fit == "cover":
        return ImageOps.fit(image, size, method=Image.Resampling.LANCZOS)
    if fit == "stretch":
        return image.resize(size, Image.Resampling.LANCZOS)

    contained = ImageOps.contain(image, size, method=Image.Resampling.LANCZOS)
    canvas = Image.new("L", size, background)
    offset = ((size[0] - contained.width) // 2, (size[1] - contained.height) // 2)
    canvas.paste(contained, offset)
    return canvas


def output_path_for(
    source: Path,
    input_root: Path,
    output_root: Path,
    output_format: str,
) -> Path:
    relative = source.relative_to(input_root)
    suffix = ".jpg" if output_format == "jpeg" else ".png"
    return (output_root / relative).with_suffix(suffix)


def discover_images(input_root: Path) -> list[Path]:
    return sorted(
        path
        for path in input_root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in SUPPORTED_SUFFIXES
        and not path.name.startswith("._")
    )


def prepare_image(
    source: Path,
    *,
    size: tuple[int, int],
    fit: str,
    background: int,
    preset: str = "none",
    autocontrast_cutoff: float | None = None,
    sigmoid: float | None = None,
    sigmoid_midpoint: float | None = None,
    gamma: float | None = None,
    brightness: float | None = None,
    contrast: float | None = None,
    sharpness: float | None = None,
    dither: str,
    levels: int,
) -> Image.Image:
    recipe = TONE_PRESETS[preset]
    sigmoid_midpoint = recipe["sigmoid_midpoint"] if sigmoid_midpoint is None else sigmoid_midpoint
    gamma = recipe["gamma"] if gamma is None else gamma
    brightness = recipe["brightness"] if brightness is None else brightness
    contrast = recipe["contrast"] if contrast is None else contrast
    sharpness = recipe["sharpness"] if sharpness is None else sharpness
    cutoff, sigmoid_strength = resolve_tone_settings(
        preset,
        autocontrast_cutoff,
        sigmoid,
    )
    try:
        opened = Image.open(source)
    except UnidentifiedImageError as exc:
        if source.suffix.lower() in {".heic", ".heif"} and not HEIF_SUPPORT:
            raise RuntimeError(
                "HEIC support is not installed; run: "
                ".venv/bin/python -m pip install -r tools/requirements.txt"
            ) from exc
        raise
    with opened:
        # Explicitly use the first frame for GIF, HEIC, and other containers.
        opened.seek(0)
        # Honor phone/camera EXIF orientation before any crop or resize.
        image = ImageOps.exif_transpose(opened)
        # Composite transparency against the requested matte before grayscale.
        if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
            rgba = image.convert("RGBA")
            matte = Image.new("RGBA", rgba.size, (background,) * 3 + (255,))
            image = Image.alpha_composite(matte, rgba)
        image = image.convert("L")
        image = fit_image(image, size, fit, background)
        image = apply_tone(
            image,
            autocontrast_cutoff=cutoff,
            sigmoid=sigmoid_strength,
            sigmoid_midpoint=sigmoid_midpoint,
            gamma=gamma,
            brightness=brightness,
            contrast=contrast,
            sharpness=sharpness,
        )
        return apply_dither(image, dither, levels)


def process_one(
    source: Path,
    destination: Path,
    *,
    size: tuple[int, int],
    fit: str,
    background: int,
    preset: str = "none",
    autocontrast_cutoff: float | None = None,
    sigmoid: float | None = None,
    sigmoid_midpoint: float | None = None,
    gamma: float | None = None,
    brightness: float | None = None,
    contrast: float | None = None,
    sharpness: float | None = None,
    dither: str,
    levels: int,
    output_format: str,
    jpeg_quality: int,
) -> None:
    image = prepare_image(
        source,
        size=size,
        fit=fit,
        background=background,
        preset=preset,
        autocontrast_cutoff=autocontrast_cutoff,
        sigmoid=sigmoid,
        sigmoid_midpoint=sigmoid_midpoint,
        gamma=gamma,
        brightness=brightness,
        contrast=contrast,
        sharpness=sharpness,
        dither=dither,
        levels=levels,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    if output_format == "jpeg":
        image.save(
            destination,
            format="JPEG",
            quality=jpeg_quality,
            optimize=True,
            progressive=False,
        )
    else:
        # optimize costs time only on the preprocessing computer, not Kindle.
        image.save(destination, format="PNG", optimize=True, compress_level=9)

    # Fail loudly if an encoder/plugin produced an unexpected result.
    with Image.open(destination) as check:
        if check.size != size:
            raise RuntimeError(f"wrong output size for {destination}: {check.size}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def process_directory(
    input_root: Path,
    output_root: Path,
    *,
    size: tuple[int, int] = PW3_SIZE,
    fit: str = "cover",
    background: int = 255,
    preset: str = "none",
    autocontrast_cutoff: float | None = None,
    sigmoid: float | None = None,
    sigmoid_midpoint: float | None = None,
    gamma: float | None = None,
    brightness: float | None = None,
    contrast: float | None = None,
    sharpness: float | None = None,
    dither: str = "none",
    levels: int | None = None,
    output_format: str | None = None,
    jpeg_quality: int = 88,
    overwrite: bool = False,
    device: str | None = None,
    on_converted=None,
) -> dict[str, object]:
    recipe = TONE_PRESETS[preset]
    autocontrast_cutoff = recipe["autocontrast_cutoff"] if autocontrast_cutoff is None else autocontrast_cutoff
    sigmoid = recipe["sigmoid"] if sigmoid is None else sigmoid
    sigmoid_midpoint = recipe["sigmoid_midpoint"] if sigmoid_midpoint is None else sigmoid_midpoint
    gamma = recipe["gamma"] if gamma is None else gamma
    brightness = recipe["brightness"] if brightness is None else brightness
    contrast = recipe["contrast"] if contrast is None else contrast
    sharpness = recipe["sharpness"] if sharpness is None else sharpness
    levels = recipe["levels"] if levels is None else levels
    output_format = recipe["output_format"] if output_format is None else output_format
    input_root = input_root.expanduser().resolve()
    output_root = output_root.expanduser().resolve()
    if not input_root.is_dir():
        raise ValueError(f"input directory does not exist: {input_root}")
    if input_root == output_root or input_root in output_root.parents:
        raise ValueError("output must not be the input directory or a child of it")
    if output_format == "jpeg" and dither != "none":
        raise ValueError("pre-dithered output should use PNG; JPEG artifacts damage the dither pattern")

    sources = discover_images(input_root)
    output_root.mkdir(parents=True, exist_ok=True)
    rows: list[tuple[str, str, int, str]] = []
    errors: list[str] = []
    failure_rows: list[tuple[str, str]] = []
    converted = skipped = 0

    options = {
        "device": device or next(
            (key for key, profile in DEVICE_PROFILES.items() if profile["size"] == size),
            "custom",
        ),
        "size": list(size),
        "fit": fit,
        "background": background,
        "preset": preset,
        "autocontrast_cutoff": autocontrast_cutoff,
        "sigmoid": sigmoid,
        "sigmoid_midpoint": sigmoid_midpoint,
        "gamma": gamma,
        "brightness": brightness,
        "contrast": contrast,
        "sharpness": sharpness,
        "dither": dither,
        "levels": levels,
        "output_format": output_format,
        "jpeg_quality": jpeg_quality,
    }

    for source in sources:
        destination = output_path_for(source, input_root, output_root, output_format)
        if destination.exists() and not overwrite:
            skipped += 1
        else:
            try:
                process_one(
                    source,
                    destination,
                    size=size,
                    fit=fit,
                    background=background,
                    preset=preset,
                    autocontrast_cutoff=autocontrast_cutoff,
                    sigmoid=sigmoid,
                    sigmoid_midpoint=sigmoid_midpoint,
                    gamma=gamma,
                    brightness=brightness,
                    contrast=contrast,
                    sharpness=sharpness,
                    dither=dither,
                    levels=levels,
                    output_format=output_format,
                    jpeg_quality=jpeg_quality,
                )
            except Exception as exc:  # keep processing a large photo library
                errors.append(f"{source}: {exc}")
                failure_rows.append((str(source.relative_to(input_root)), str(exc)))
                continue
            converted += 1
            if on_converted:
                on_converted(source, destination)
        rows.append(
            (
                str(source.relative_to(input_root)),
                str(destination.relative_to(output_root)),
                destination.stat().st_size,
                sha256(destination),
            )
        )

    manifest_path = output_root / "manifest.tsv"
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(("source", "output", "bytes", "sha256"))
        writer.writerows(rows)
    settings_path = output_root / "processing-settings.json"
    settings_path.write_text(json.dumps(options, indent=2) + "\n", encoding="utf-8")
    failures_path = output_root / "failures.tsv"
    with failures_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(("source", "error"))
        writer.writerows(failure_rows)

    return {
        "converted": converted,
        "skipped": skipped,
        "failed": len(errors),
        "discovered": len(sources),
        "errors": errors,
        "manifest": str(manifest_path),
        "settings": str(settings_path),
        "failures": str(failures_path),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Resize, orient, and grayscale photos before copying them to a Kindle.",
    )
    parser.add_argument("input", type=Path, help="source photo directory")
    parser.add_argument("output", type=Path, help="destination directory")
    parser.add_argument(
        "--device",
        choices=tuple(DEVICE_PROFILES),
        default="pw3",
        help="target Kindle profile (default: pw3)",
    )
    parser.add_argument("--size", type=parse_size, default=None, help="custom output size; overrides --device")
    parser.add_argument("--fit", choices=("cover", "contain", "stretch"), default="cover")
    parser.add_argument("--background", type=int, choices=range(256), default=255, metavar="0..255")
    parser.add_argument("--preset", choices=tuple(TONE_PRESETS), default="none")
    parser.add_argument("--autocontrast-cutoff", type=float, default=None, metavar="PERCENT")
    parser.add_argument("--sigmoid", type=float, default=None, metavar="STRENGTH")
    parser.add_argument("--sigmoid-midpoint", type=float, default=None, metavar="0..1")
    parser.add_argument("--gamma", type=float, default=None, help="above 1 brightens midtones")
    parser.add_argument("--brightness", type=float, default=None)
    parser.add_argument("--contrast", type=float, default=None)
    parser.add_argument("--sharpness", type=float, default=None)
    parser.add_argument("--format", choices=("jpeg", "png"), default=None, dest="output_format")
    parser.add_argument("--jpeg-quality", type=int, choices=range(1, 96), default=88, metavar="1..95")
    parser.add_argument("--dither", choices=("none", "floyd-steinberg"), default="none")
    parser.add_argument("--levels", type=int, choices=range(2, 257), default=None, metavar="2..256")
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    input_root = args.input.expanduser().resolve()
    output_root = args.output.expanduser().resolve()
    size = args.size or DEVICE_PROFILES[args.device]["size"]
    try:
        result = process_directory(
            input_root,
            output_root,
            size=size,
            fit=args.fit,
            background=args.background,
            preset=args.preset,
            autocontrast_cutoff=args.autocontrast_cutoff,
            sigmoid=args.sigmoid,
            sigmoid_midpoint=args.sigmoid_midpoint,
            gamma=args.gamma,
            brightness=args.brightness,
            contrast=args.contrast,
            sharpness=args.sharpness,
            dither=args.dither,
            levels=args.levels,
            output_format=args.output_format,
            jpeg_quality=args.jpeg_quality,
            overwrite=args.overwrite,
            device=args.device if args.size is None else "custom",
            on_converted=lambda source, destination: print(f"{source} -> {destination}"),
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    for error in result["errors"]:
        print(f"ERROR {error}", file=sys.stderr)
    print(
        f"converted={result['converted']} skipped={result['skipped']} "
        f"failed={result['failed']} discovered={result['discovered']}"
    )
    print(f"manifest={result['manifest']}")
    print(f"settings={result['settings']}")
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
