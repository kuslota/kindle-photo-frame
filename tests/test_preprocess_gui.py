from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


TOOLS = Path(__file__).parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
SCRIPT = TOOLS / "preprocess_gui.py"
SPEC = importlib.util.spec_from_file_location("preprocess_gui", SCRIPT)
assert SPEC and SPEC.loader
preprocess_gui = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preprocess_gui)


class PreprocessGuiTest(unittest.TestCase):
    def test_preset_file_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "presets.json"
            expected = {"Bright family": {"gamma": 1.15, "contrast": 1.2}}
            preprocess_gui.write_presets(path, expected)
            self.assertEqual(preprocess_gui.load_presets(path), expected)

    def test_saved_settings_exclude_paths_and_overwrite(self) -> None:
        settings = preprocess_gui.saved_settings_from_payload(
            {
                "preset": "medium",
                "input_dir": "/private/photos",
                "output_dir": "/private/output",
                "overwrite": True,
            }
        )
        self.assertNotIn("input_dir", settings)
        self.assertNotIn("output_dir", settings)
        self.assertNotIn("overwrite", settings)
        self.assertEqual(settings["device"], "pw3")
        self.assertEqual(settings["autocontrast_cutoff"], 5.0)

    def test_scribe_payload_selects_scribe_resolution(self) -> None:
        settings = preprocess_gui.options_from_payload({"device": "scribe1"})
        self.assertEqual(settings["device"], "scribe1")
        self.assertEqual(settings["size"], (1860, 2480))

    def test_all_profiles_are_exposed_by_gui_options(self) -> None:
        for device, profile in preprocess_gui.preprocess_images.DEVICE_PROFILES.items():
            settings = preprocess_gui.options_from_payload({"device": device})
            self.assertEqual(settings["device"], device)
            self.assertEqual(settings["size"], profile["size"])

    def test_custom_resolution_is_validated_and_saved(self) -> None:
        settings = preprocess_gui.options_from_payload(
            {"device": "custom", "custom_width": "1200", "custom_height": "1600"}
        )
        self.assertEqual(settings["size"], (1200, 1600))
        saved = preprocess_gui.saved_settings_from_payload(
            {"device": "custom", "custom_width": 1200, "custom_height": 1600}
        )
        self.assertEqual(saved["custom_width"], 1200)
        self.assertEqual(saved["custom_height"], 1600)
        for key, value in (("custom_width", 0), ("custom_height", 10001), ("custom_width", "wide")):
            with self.assertRaises(ValueError):
                preprocess_gui.options_from_payload({"device": "custom", key: value})

    def test_preset_name_is_trimmed_and_validated(self) -> None:
        self.assertEqual(preprocess_gui.normalize_preset_name("  Portraits  "), "Portraits")
        with self.assertRaises(ValueError):
            preprocess_gui.normalize_preset_name("  ")


if __name__ == "__main__":
    unittest.main()
