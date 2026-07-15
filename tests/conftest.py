import sys
from pathlib import Path

# make `bhtom_uploader` and `tests.fixtures` importable regardless of invocation dir
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
