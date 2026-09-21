#!/usr/bin/env python3
"""Local browser UI for previewing and exporting Kindle-ready photos."""

from __future__ import annotations

import argparse
import base64
import io
import json
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, ImageStat

import preprocess_images
from app_paths import resource_path, user_data_dir, default_output_dirs


HTML_PATH = resource_path("preprocess_gui.html")
DEFAULT_PRESETS_PATH = user_data_dir() / "presets.json"
SAVED_SETTING_KEYS = (
    "device",
    "custom_width",
    "custom_height",
    "fit",
    "background",
    "autocontrast_cutoff",
    "sigmoid",
    "sigmoid_midpoint",
    "gamma",
    "brightness",
    "contrast",
    "sharpness",
    "dither",
    "levels",
    "output_format",
    "jpeg_quality",
)


def number(payload: dict[str, Any], key: str, default: float) -> float:
    value = payload.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a number") from exc


def integer(payload: dict[str, Any], key: str, default: int) -> int:
    value = payload.get(key, default)
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be an integer") from exc


def custom_dimension(payload: dict[str, Any], key: str) -> int:
    value = integer(payload, key, 1072)
    if not 1 <= value <= 10000:
        raise ValueError(f"{key} must be from 1 through 10000 pixels")
    return value


def options_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    device = str(payload.get("device", "pw3"))
    preset = str(payload.get("preset", "medium"))
    if preset not in preprocess_images.TONE_PRESETS:
        raise ValueError("unknown contrast preset")
    payload = {**preprocess_images.TONE_PRESETS[preset], **payload}
    fit = str(payload.get("fit", "cover"))
    output_format = str(payload.get("output_format", "jpeg"))
    dither = str(payload.get("dither", "none"))
    if device not in preprocess_images.DEVICE_PROFILES and device != "custom":
        raise ValueError("unknown Kindle device profile")
    if preset not in preprocess_images.TONE_PRESETS:
        raise ValueError("unknown contrast preset")
    if fit not in {"cover", "contain", "stretch"}:
        raise ValueError("unknown fit mode")
    if output_format not in {"jpeg", "png"}:
        raise ValueError("unknown output format")
    if dither not in {"none", "floyd-steinberg"}:
        raise ValueError("unknown dither mode")

    custom_width = custom_dimension(payload, "custom_width")
    custom_height = custom_dimension(payload, "custom_height")
    options = {
        "device": device,
        "size": ((custom_width, custom_height) if device == "custom"
                 else preprocess_images.DEVICE_PROFILES[device]["size"]),
        "custom_width": custom_width,
        "custom_height": custom_height,
        "fit": fit,
        "background": integer(payload, "background", 255),
        "preset": preset,
        # The GUI always sends explicit values. Choosing a preset updates them.
        "autocontrast_cutoff": number(payload, "autocontrast_cutoff", 1.5),
        "sigmoid": number(payload, "sigmoid", 3.0),
        "sigmoid_midpoint": number(payload, "sigmoid_midpoint", 0.5),
        "gamma": number(payload, "gamma", 1.0),
        "brightness": number(payload, "brightness", 1.0),
        "contrast": number(payload, "contrast", 1.0),
        "sharpness": number(payload, "sharpness", 1.0),
        "dither": dither,
        "levels": integer(payload, "levels", 16),
        "output_format": output_format,
        "jpeg_quality": integer(payload, "jpeg_quality", 88),
    }
    if not 0 <= options["background"] <= 255:
        raise ValueError("background must be from 0 through 255")
    if not 2 <= options["levels"] <= 256:
        raise ValueError("levels must be from 2 through 256")
    if not 1 <= options["jpeg_quality"] <= 95:
        raise ValueError("JPEG quality must be from 1 through 95")
    if output_format == "jpeg" and dither != "none":
        raise ValueError("dithered output must use PNG")
    return options


def load_presets(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("presets"), dict):
        raise ValueError(f"invalid preset file: {path}")
    return {
        str(name): settings
        for name, settings in data["presets"].items()
        if isinstance(name, str) and isinstance(settings, dict)
    }


def write_presets(path: Path, presets: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    data = {
        "version": 1,
        "presets": dict(sorted(presets.items(), key=lambda item: item[0].casefold())),
    }
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def normalize_preset_name(value: object) -> str:
    name = str(value or "").strip()
    if not name:
        raise ValueError("enter a name for the preset")
    if len(name) > 60:
        raise ValueError("preset names may contain at most 60 characters")
    if any(ord(character) < 32 for character in name):
        raise ValueError("preset names cannot contain control characters")
    return name


def saved_settings_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    options = options_from_payload(payload)
    return {key: options[key] for key in SAVED_SETTING_KEYS}


def encode_preview(image: Image.Image) -> str:
    preview = image.copy()
    preview.thumbnail((536, 724), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    preview.save(buffer, format="JPEG", quality=90)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


class PhotoFrameHandler(BaseHTTPRequestHandler):
    defaults: dict[str, Any] = {}
    presets_path: Path = DEFAULT_PRESETS_PATH
    presets_lock = threading.Lock()
    folder_picker = None

    def trusted_request(self) -> bool:
        expected = f"127.0.0.1:{self.server.server_port}"
        return (self.headers.get("Host") == expected
                and self.headers.get("Origin", f"http://{expected}") == f"http://{expected}")

    def log_message(self, format: str, *args: object) -> None:
        return

    def send_json(self, data: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 <= length <= 1024 * 1024:
            raise ValueError("request is too large")
        value = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(value, dict):
            raise ValueError("request must be a JSON object")
        return value

    def do_GET(self) -> None:
        if not self.trusted_request():
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if self.path == "/":
            body = HTML_PATH.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/api/defaults":
            self.send_json(self.defaults)
            return
        if self.path == "/api/presets":
            try:
                with self.presets_lock:
                    self.send_json({"presets": load_presets(self.presets_path)})
            except (ValueError, OSError) as exc:
                self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if not self.trusted_request() or self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        try:
            payload = self.read_json()
            if self.path == "/api/choose-folder":
                if self.folder_picker is None:
                    raise ValueError("Folder dialogs are unavailable in headless mode.")
                kind = payload.get("kind")
                if kind not in {"input", "output"}:
                    raise ValueError("unknown folder choice")
                chosen = self.folder_picker.choose("Choose photos" if kind == "input" else "Choose where to save prepared photos")
                self.send_json({"path": chosen})
            elif self.path == "/api/quit":
                self.send_json({"stopped": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            elif self.path == "/api/scan":
                self.scan(payload)
            elif self.path == "/api/preview":
                self.preview(payload)
            elif self.path == "/api/process":
                self.process(payload)
            elif self.path == "/api/presets/save":
                self.save_preset(payload)
            elif self.path == "/api/presets/delete":
                self.delete_preset(payload)
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self.send_json({"error": f"Processing failed: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def scan(self, payload: dict[str, Any]) -> None:
        if not str(payload.get("input_dir", "")).strip():
            raise ValueError("Choose a photo folder first.")
        input_root = Path(str(payload.get("input_dir", ""))).expanduser().resolve()
        if not input_root.is_dir():
            raise ValueError(f"input directory does not exist: {input_root}")
        sources = preprocess_images.discover_images(input_root)
        images = []
        for source in sources:
            try:
                metadata = source.stat()
            except FileNotFoundError:
                # A file may be renamed or removed while an automatic scan runs.
                continue
            images.append(
                {
                    "path": str(source),
                    "name": str(source.relative_to(input_root)),
                    "bytes": metadata.st_size,
                    "modified_ns": metadata.st_mtime_ns,
                }
            )
        self.send_json(
            {
                "input_dir": str(input_root),
                "images": images,
            }
        )

    def preview(self, payload: dict[str, Any]) -> None:
        source = Path(str(payload.get("source", ""))).expanduser().resolve()
        if not source.is_file() or source.suffix.lower() not in preprocess_images.SUPPORTED_SUFFIXES:
            raise ValueError("select a supported source image")
        options = options_from_payload(payload)
        with Image.open(source) as opened:
            opened.seek(0)
            original = ImageOps.exif_transpose(opened)
            if original.mode in {"RGBA", "LA"} or "transparency" in original.info:
                rgba = original.convert("RGBA")
                matte = Image.new("RGBA", rgba.size, "white")
                original = Image.alpha_composite(matte, rgba)
            original = original.convert("RGB")
        image = preprocess_images.prepare_image(
            source,
            **{
                key: value
                for key, value in options.items()
                if key not in {"device", "custom_width", "custom_height", "output_format", "jpeg_quality"}
            },
        )
        stats = ImageStat.Stat(image)
        histogram = image.histogram()
        pixel_count = image.width * image.height
        clipped_black = sum(histogram[:4]) * 100.0 / pixel_count
        clipped_white = sum(histogram[252:]) * 100.0 / pixel_count
        self.send_json(
            {
                "source_image": encode_preview(original),
                "image": encode_preview(image),
                "mean": round(stats.mean[0], 1),
                "standard_deviation": round(stats.stddev[0], 1),
                "black_clip": round(clipped_black, 2),
                "white_clip": round(clipped_white, 2),
            }
        )

    def process(self, payload: dict[str, Any]) -> None:
        if not str(payload.get("input_dir", "")).strip():
            raise ValueError("Choose a photo folder first.")
        input_root = Path(str(payload.get("input_dir", ""))).expanduser().resolve()
        if not str(payload.get("output_dir", "")).strip():
            raise ValueError("Choose an export folder first.")
        output_root = Path(str(payload.get("output_dir", ""))).expanduser().resolve()
        if output_root in input_root.parents:
            raise ValueError("Choose an export folder separate from your source photos.")
        options = options_from_payload(payload)
        result = preprocess_images.process_directory(
            input_root,
            output_root,
            overwrite=bool(payload.get("overwrite", False)),
            **{
                key: value
                for key, value in options.items()
                if key not in {"custom_width", "custom_height"}
            },
        )
        self.send_json(result)

    def save_preset(self, payload: dict[str, Any]) -> None:
        name = normalize_preset_name(payload.get("name"))
        settings = saved_settings_from_payload(payload)
        with self.presets_lock:
            presets = load_presets(self.presets_path)
            presets[name] = settings
            write_presets(self.presets_path, presets)
        self.send_json({"saved": name, "presets": presets})

    def delete_preset(self, payload: dict[str, Any]) -> None:
        name = normalize_preset_name(payload.get("name"))
        with self.presets_lock:
            presets = load_presets(self.presets_path)
            if name not in presets:
                raise ValueError(f"preset does not exist: {name}")
            del presets[name]
            write_presets(self.presets_path, presets)
        self.send_json({"deleted": name, "presets": presets})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Open the Kindle photo preprocessing GUI.")
    parser.add_argument("--self-test", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--input", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--device", choices=tuple(preprocess_images.DEVICE_PROFILES), default="pw3")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--presets", type=Path, default=DEFAULT_PRESETS_PATH)
    parser.add_argument("--no-browser", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.self_test:
        from packaged_checks import run
        try:
            run(args.self_test)
        except Exception:
            import traceback
            args.self_test.write_text(json.dumps({"ok": False, "error": traceback.format_exc()}), encoding="utf-8")
            return 1
        return 0
    output_dirs = default_output_dirs()
    selected_output = args.output or output_dirs[args.device]
    PhotoFrameHandler.defaults = {
        "input_dir": str(args.input.expanduser().resolve()) if args.input else "",
        "output_dir": str(selected_output.expanduser().resolve()),
        "device": args.device,
        "presets": preprocess_images.TONE_PRESETS,
        "output_dirs": {
            device: str(path.expanduser().resolve()) for device, path in output_dirs.items()
        },
        "device_profiles": {
            device: {"label": profile["label"], "size": list(profile["size"])}
            for device, profile in preprocess_images.DEVICE_PROFILES.items()
        },
    }
    PhotoFrameHandler.presets_path = args.presets.expanduser().resolve()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), PhotoFrameHandler)
    url = f"http://127.0.0.1:{server.server_port}/"
    picker = None
    if not args.no_browser:
        from folder_picker import FolderPicker
        picker = FolderPicker()
    PhotoFrameHandler.folder_picker = picker
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        if picker:
            from tkinter import messagebox
            if not webbrowser.open(url):
                messagebox.showinfo("Kindle Photo Prep", f"Open your browser at {url}", parent=picker.root)
            def check_server():
                if worker.is_alive():
                    picker.root.after(200, check_server)
                else:
                    picker.root.quit()
            picker.root.after(200, check_server)
            picker.root.mainloop()
        else:
            print(f"Kindle Photo Prep: {url}", flush=True)
            worker.join()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        if picker:
            picker.root.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
