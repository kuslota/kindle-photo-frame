from __future__ import annotations
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch, Mock
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).parents[1] / 'tools'))
import app_paths
import package_plugin
import preprocess_gui
from PIL import Image


class PathTests(unittest.TestCase):
    def test_resources_source_and_relocated_bundle(self):
        self.assertTrue(app_paths.resource_path('preprocess_gui.html').is_file())
        # Use a native absolute path, including the drive on Windows.
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary).resolve() / 'relocated' / 'app' / '_internal'
            with patch.object(app_paths, '__file__', str(bundle / 'app_paths.py')):
                self.assertEqual(app_paths.resource_path('preprocess_gui.html'),
                                 bundle / 'preprocess_gui.html')

    def test_user_paths(self):
        # Changing sys.platform selects the app's OS branch, but does not
        # change pathlib's host-specific path syntax. Keep fixtures native.
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            home = base / 'users' / 'example'
            local_data = base / 'writable' / 'local'
            xdg_data = base / 'custom' / 'data'
            self.assertTrue(xdg_data.is_absolute())
            with patch.object(Path, 'home', return_value=home):
                with patch.object(sys, 'platform', 'darwin'):
                    self.assertEqual(app_paths.user_data_dir(),
                                     home / 'Library' / 'Application Support' / 'Kindle Photo Prep')
                with patch.object(sys, 'platform', 'win32'), patch.dict('os.environ', {'LOCALAPPDATA': str(local_data)}):
                    self.assertEqual(app_paths.user_data_dir(), local_data / 'Kindle Photo Prep')
                with patch.object(sys, 'platform', 'linux'), patch.dict('os.environ', {'XDG_DATA_HOME': str(xdg_data)}):
                    self.assertEqual(app_paths.user_data_dir(), xdg_data / 'Kindle Photo Prep')
                with patch.object(sys, 'platform', 'linux'), patch.dict('os.environ', {'XDG_DATA_HOME': 'relative'}):
                    self.assertEqual(app_paths.user_data_dir(), home / '.local' / 'share' / 'Kindle Photo Prep')
                outputs = app_paths.default_output_dirs()
                self.assertEqual(set(outputs), set(preprocess_gui.preprocess_images.DEVICE_PROFILES) | {'custom'})
                self.assertNotEqual(outputs['pw3'], outputs['scribe1'])
                self.assertTrue(all(home in p.parents for p in outputs.values()))

    def test_plugin_archive_is_copy_ready(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = package_plugin.package_plugin(Path(temporary) / 'plugin.zip')
            with ZipFile(path) as archive:
                self.assertEqual(set(archive.namelist()), {
                    'photo_frame.koplugin/main.lua', 'photo_frame.koplugin/_meta.lua',
                    'photo_frame.koplugin/README.md', 'photo_frame.koplugin/LICENSE'})
                self.assertIn(b'PhotoFrame', archive.read('photo_frame.koplugin/main.lua'))

    def test_port_is_allocated_by_os(self):
        self.assertEqual(preprocess_gui.build_parser().parse_args([]).port, 0)


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / 'Photos é with spaces'
        self.source.mkdir()
        Image.new('RGB', (32, 48), 'gray').save(self.source / 'photo.png')
        self.picker = Mock()
        handler = type('TestHandler', (preprocess_gui.PhotoFrameHandler,),
                       {'folder_picker': self.picker, 'presets_path': self.root / 'presets.json'})
        self.server = preprocess_gui.ThreadingHTTPServer(('127.0.0.1', 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temporary.cleanup()

    def post(self, path, payload, headers=None):
        request = urllib.request.Request(self.url + path, json.dumps(payload).encode(),
                    headers or {'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.load(response)

    def test_picker_select_and_cancel(self):
        self.picker.choose.return_value = str(self.source)
        self.assertEqual(self.post('/api/choose-folder', {'kind': 'input'})['path'], str(self.source))
        self.picker.choose.return_value = ''
        self.assertEqual(self.post('/api/choose-folder', {'kind': 'output'})['path'], '')

    def test_reject_foreign_origin_host_and_simple_post(self):
        for headers in [
            {'Content-Type': 'application/json', 'Origin': 'https://example.com'},
            {'Content-Type': 'application/json', 'Host': 'example.com'},
            {'Content-Type': 'text/plain'},
        ]:
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.post('/api/choose-folder', {'kind': 'input'}, headers)
            self.assertEqual(error.exception.code, 403)
            error.exception.close()
        self.picker.choose.assert_not_called()

    def test_empty_and_overlapping_paths_rejected(self):
        for source, output in [('', str(self.root / 'out')), (str(self.source), ''),
                               (str(self.source), str(self.source)),
                               (str(self.source), str(self.source / 'out')),
                               (str(self.source), str(self.root))]:
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.post('/api/process', {'input_dir': source, 'output_dir': output})
            self.assertEqual(error.exception.code, 400)
            error.exception.close()

    def test_export_with_unicode_spaces_and_no_overwrite(self):
        output = self.root / 'Prepared é'
        payload = {'input_dir': str(self.source), 'output_dir': str(output), 'device': 'scribe1'}
        result = self.post('/api/process', payload)
        self.assertEqual(result['converted'], 1)
        with Image.open(output / 'photo.jpg') as image:
            self.assertEqual(image.size, (1860, 2480))
        self.assertEqual(self.post('/api/process', payload)['skipped'], 1)
        self.assertTrue((self.source / 'photo.png').exists())

    def test_custom_resolution_export(self):
        output = self.root / 'Prepared custom'
        result = self.post('/api/process', {
            'input_dir': str(self.source),
            'output_dir': str(output),
            'device': 'custom',
            'custom_width': 900,
            'custom_height': 1200,
        })
        self.assertEqual(result['converted'], 1)
        with Image.open(output / 'photo.jpg') as image:
            self.assertEqual(image.size, (900, 1200))
