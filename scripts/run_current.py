import runpy,sys
from pathlib import Path
p=Path(__file__).resolve().parent/"clean-v11"
sys.path.insert(0,str(p))
runpy.run_path(str(p/"run_current.py"),run_name="__main__")
