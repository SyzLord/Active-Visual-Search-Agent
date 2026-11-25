"""Load the frozen engine and the prior experiment as sibling directories."""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
PREVIOUS = HERE.parent/"页底印章年份复读_2026-11-18_晚间"
sys.path.insert(0,str(PREVIOUS))
