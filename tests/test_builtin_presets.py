import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / 'tools'))
import preprocess_gui
import preprocess_images
from PIL import Image


class BuiltinPresetTests(unittest.TestCase):
    def test_complete_recipes_and_device_independence(self):
        common = dict(fit='cover', background=255, sigmoid_midpoint=0.5,
                      brightness=1.0, sharpness=1.5, dither='none', levels=200,
                      jpeg_quality=88)
        recipes = {
            'medium': dict(common, autocontrast_cutoff=5.0, sigmoid=5.4,
                           gamma=1.7, contrast=0.85, output_format='jpeg'),
            'strong': dict(common, autocontrast_cutoff=6.0, sigmoid=6.3,
                           gamma=2.15, contrast=0.9, output_format='png'),
        }
        for name, expected in recipes.items():
            self.assertEqual(preprocess_images.TONE_PRESETS[name], expected)
            for device in ('pw3', 'scribe1'):
                options = preprocess_gui.options_from_payload({'preset': name, 'device': device})
                self.assertEqual(options['device'], device)
                for key, value in expected.items():
                    self.assertEqual(options[key], value)

    def test_cli_exports_full_recipes_and_honors_overrides(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            source.mkdir()
            Image.linear_gradient('L').save(source / 'photo.png')
            for name, suffix in [('medium', 'jpg'), ('strong', 'png')]:
                output = root / name
                with contextlib.redirect_stdout(io.StringIO()):
                    preprocess_images.main([str(source), str(output), '--preset', name])
                self.assertTrue((output / ('photo.' + suffix)).is_file())
                settings = json.loads((output / 'processing-settings.json').read_text())
                for key, value in preprocess_images.TONE_PRESETS[name].items():
                    self.assertEqual(settings[key], value)
            with contextlib.redirect_stdout(io.StringIO()):
                preprocess_images.main([str(source), str(root / 'custom'), '--preset', 'strong',
                                        '--gamma', '1.2', '--format', 'jpeg'])
            settings = json.loads((root / 'custom' / 'processing-settings.json').read_text())
            self.assertEqual(settings['gamma'], 1.2)
            self.assertTrue((root / 'custom' / 'photo.jpg').exists())
