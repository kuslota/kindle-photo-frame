from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from PIL import Image


SCRIPT = Path(__file__).parents[1] / "tools" / "preprocess_images.py"
SPEC = importlib.util.spec_from_file_location("preprocess_images", SCRIPT)
assert SPEC and SPEC.loader
preprocess_images = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preprocess_images)


class PreprocessImagesTest(unittest.TestCase):
    def test_heif_decoder_is_registered(self) -> None:
        self.assertTrue(preprocess_images.HEIF_SUPPORT)
        self.assertEqual(Image.registered_extensions().get(".heic"), "HEIF")

    def test_device_profiles_have_expected_native_sizes(self) -> None:
        expected = {
            "basic_older": (600, 800),
            "basic_11": (1072, 1448),
            "pw1_2": (758, 1024),
            "pw3": (1072, 1448),
            "pw4": (1072, 1448),
            "voyage": (1072, 1448),
            "oasis1": (1072, 1448),
            "pw5": (1236, 1648),
            "oasis2_3": (1264, 1680),
            "scribe1": (1860, 2480),
        }
        self.assertEqual(
            {key: profile["size"] for key, profile in preprocess_images.DEVICE_PROFILES.items()},
            expected,
        )
        self.assertTrue(all(width > 0 and height > 0 for width, height in expected.values()))

    def test_every_device_profile_can_process_an_image(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.png"
            Image.new("RGB", (120, 80), "gray").save(source)
            for device, profile in preprocess_images.DEVICE_PROFILES.items():
                output = root / f"{device}.jpg"
                preprocess_images.process_one(
                    source,
                    output,
                    size=profile["size"],
                    fit="cover",
                    background=255,
                    dither="none",
                    levels=16,
                    output_format="jpeg",
                    jpeg_quality=88,
                )
                with Image.open(output) as result:
                    self.assertEqual(result.size, profile["size"], device)

    def test_cover_jpeg_is_exact_size_and_grayscale(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.png"
            output = root / "output.jpg"
            Image.new("RGB", (120, 80), "red").save(source)

            preprocess_images.process_one(
                source,
                output,
                size=(1072, 1448),
                fit="cover",
                background=255,
                dither="none",
                levels=16,
                output_format="jpeg",
                jpeg_quality=88,
            )

            with Image.open(output) as result:
                self.assertEqual(result.size, (1072, 1448))
                self.assertEqual(result.mode, "L")

    def test_contain_adds_white_matte(self) -> None:
        image = Image.new("L", (200, 100), 0)
        result = preprocess_images.fit_image(image, (100, 100), "contain", 255)
        self.assertEqual(result.size, (100, 100))
        self.assertEqual(result.getpixel((0, 0)), 255)
        self.assertEqual(result.getpixel((50, 50)), 0)

    def test_scribe_output_uses_native_portrait_size(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.jpg"
            output = root / "scribe.jpg"
            Image.new("RGB", (80, 120), "gray").save(source)
            preprocess_images.process_one(
                source,
                output,
                size=preprocess_images.DEVICE_PROFILES["scribe1"]["size"],
                fit="cover",
                background=255,
                dither="none",
                levels=16,
                output_format="jpeg",
                jpeg_quality=88,
            )
            with Image.open(output) as result:
                self.assertEqual(result.size, (1860, 2480))

    def test_floyd_steinberg_limits_output_levels(self) -> None:
        gradient = Image.linear_gradient("L").resize((64, 64))
        result = preprocess_images.apply_dither(gradient, "floyd-steinberg", 16)
        self.assertEqual(result.mode, "L")
        self.assertLessEqual(sum(count > 0 for count in result.histogram()), 16)

    def test_discovery_ignores_resource_forks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            Image.new("L", (1, 1)).save(root / "photo.jpg")
            (root / "._photo.jpg").write_bytes(b"not an image")
            (root / "notes.txt").write_text("ignore", encoding="utf-8")
            self.assertEqual(preprocess_images.discover_images(root), [root / "photo.jpg"])

    def test_medium_preset_increases_midtone_separation(self) -> None:
        gradient = Image.linear_gradient("L").resize((256, 64))
        original_difference = gradient.getpixel((128, 32)) - gradient.getpixel((128, 24))
        adjusted = preprocess_images.apply_tone(gradient, sigmoid=3.0)
        adjusted_difference = adjusted.getpixel((128, 32)) - adjusted.getpixel((128, 24))
        self.assertGreater(adjusted_difference, original_difference)

    def test_gamma_above_one_brightens_midtones(self) -> None:
        image = Image.new("L", (1, 1), 64)
        result = preprocess_images.apply_tone(image, gamma=1.5)
        self.assertGreater(result.getpixel((0, 0)), 64)

    def test_directory_export_records_processing_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_root = root / "input"
            output_root = root / "output"
            input_root.mkdir()
            Image.new("RGB", (12, 8), "gray").save(input_root / "photo.jpg")

            result = preprocess_images.process_directory(
                input_root,
                output_root,
                size=(120, 80),
                preset="strong",
            )

            self.assertEqual(result["converted"], 1)
            settings = (output_root / "processing-settings.json").read_text(encoding="utf-8")
            self.assertIn('"preset": "strong"', settings)

    def test_directory_export_writes_bounded_failure_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_root = root / "input"
            output_root = root / "output"
            input_root.mkdir()
            (input_root / "broken.jpg").write_bytes(b"not an image")

            result = preprocess_images.process_directory(input_root, output_root)

            self.assertEqual(result["failed"], 1)
            report = (output_root / "failures.tsv").read_text(encoding="utf-8")
            self.assertIn("source\terror", report)
            self.assertIn("broken.jpg", report)


if __name__ == "__main__":
    unittest.main()
