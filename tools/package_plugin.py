"""Create the copy-ready plugin archive using an explicit release allowlist."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_FILES = ('_meta.lua', 'main.lua', 'README.md')


def package_plugin(destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(destination, 'w', ZIP_DEFLATED) as archive:
        for name in PLUGIN_FILES:
            relative = Path('photo_frame.koplugin') / name
            archive.write(ROOT / relative, relative.as_posix())
        archive.write(ROOT / 'LICENSE', 'photo_frame.koplugin/LICENSE')
    return destination


if __name__ == '__main__':
    print(package_plugin(ROOT / 'dist' / 'Kindle-Photo-Frame-Plugin.zip'))
