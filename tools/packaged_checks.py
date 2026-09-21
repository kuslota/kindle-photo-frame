"""Non-interactive frozen checks; a real OS picker still requires release QA."""
import json
import tempfile
import threading
import urllib.request
from pathlib import Path
from unittest.mock import patch

import preprocess_images


def run(report: Path) -> None:
    import pillow_heif
    from PIL import Image
    from folder_picker import FolderPicker
    from preprocess_gui import PhotoFrameHandler, ThreadingHTTPServer, HTML_PATH

    assert 'Kindle Photo Prep' in HTML_PATH.read_text(encoding='utf-8')
    picker = FolderPicker()  # Actually load bundled Tcl AND Tk.
    with tempfile.TemporaryDirectory(prefix='photo-prep-') as temporary:
        base = Path(temporary)
        source = base / 'Photos with spaces é'
        source.mkdir()
        image = Image.new('RGB', (100, 200), (110, 150, 200))
        image.save(source / 'photo.png')
        pillow_heif.from_pillow(image).save(source / 'heif-photo.heic')
        # Exercise dispatch from an HTTP-style worker to the GUI main thread.
        selected = []
        with patch('tkinter.filedialog.askdirectory', return_value=str(source)):
            thread = threading.Thread(target=lambda: selected.append(picker.choose('Choose photos')))
            thread.start()
            while thread.is_alive():
                picker.root.update()
            thread.join()
        assert selected == [str(source)]
        picker.root.destroy()
        PhotoFrameHandler.presets_path = base / 'settings' / 'presets.json'
        server = ThreadingHTTPServer(('127.0.0.1', 0), PhotoFrameHandler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        url = f'http://127.0.0.1:{server.server_port}'
        def post(endpoint, body):
            request = urllib.request.Request(url + endpoint, json.dumps(body).encode(),
                                             {'Content-Type': 'application/json'})
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                assert b'Choose photo folder' in response.read()
            assert len(post('/api/scan', {'input_dir': str(source)})['images']) == 2
            for device, profile in preprocess_images.DEVICE_PROFILES.items():
                size = profile['size']
                output = base / device
                result = post('/api/process', {'input_dir': str(source),
                              'output_dir': str(output), 'device': device})
                assert result['converted'] == 2 and result['failed'] == 0, result
                for photo in output.glob('*.jpg'):
                    with Image.open(photo) as prepared:
                        assert prepared.size == size
                assert len(list(output.glob('*.jpg'))) == 2
            assert post('/api/presets/save', {'name': 'Smoke preset'})['saved'] == 'Smoke preset'
        finally:
            server.shutdown()
            server.server_close()
            worker.join()
    report.write_text(json.dumps({'ok': True, 'checks': ['HTML', 'Tk', 'picker dispatch',
                     'HEIF', 'HTTP', 'all device exports', 'presets']}), encoding='utf-8')
