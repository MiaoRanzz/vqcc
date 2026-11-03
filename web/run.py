"""Load Web-only dependencies after Conda selects the project's interpreter."""
from pathlib import Path
import runpy
import sys

root = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(root / 'web/.python'), str(root)]
module = sys.argv.pop(1)
runpy.run_module(module, run_name='__main__', alter_sys=True)
