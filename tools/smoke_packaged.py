"""Run checks using the frozen executable from an unrelated working directory."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
executable = (root / 'dist' / 'Kindle Photo Prep.app' / 'Contents' / 'MacOS' / 'Kindle Photo Prep'
              if sys.platform == 'darwin' else
              root / 'dist' / 'Kindle Photo Prep' / 'Kindle Photo Prep.exe')
with tempfile.TemporaryDirectory() as temporary:
    report = Path(temporary) / 'report.json'
    completed = subprocess.run([str(executable), '--self-test', str(report)], cwd=temporary, check=False, timeout=90)
    result = json.loads(report.read_text())
    assert completed.returncode == 0 and result['ok'], result
    print(result)
