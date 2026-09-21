# Build on the target OS with its native Python (including Tcl/Tk).
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH).parent
heif_data, heif_bins, heif_hidden = collect_all('pillow_heif')
a = Analysis([str(root / 'tools' / 'preprocess_gui.py')],
             pathex=[str(root / 'tools')],
             binaries=heif_bins,
             datas=[(str(root / 'tools' / 'preprocess_gui.html'), '.'),
                    (str(root / 'LICENSE'), '.')] + heif_data,
             hiddenimports=heif_hidden + ['tkinter', 'tkinter.filedialog', 'tkinter.messagebox'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='Kindle Photo Prep',
          console=False, target_arch=None, codesign_identity=None, entitlements_file=None)
collection = COLLECT(exe, a.binaries, a.datas, name='Kindle Photo Prep')
if sys.platform == 'darwin':
    app = BUNDLE(collection, name='Kindle Photo Prep.app',
                 bundle_identifier='io.github.kuslota.kindlephotoprep',
                 info_plist={'CFBundleShortVersionString': '1.0.0',
                             'NSHighResolutionCapable': True})
