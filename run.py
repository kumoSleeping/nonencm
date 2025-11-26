import sys
from pathlib import Path

# Add current directory to sys.path
sys.path.append(str(Path(__file__).parent))

from app.__main__ import main

if __name__ == "__main__":
    main()
