import asyncio
import sys
from pathlib import Path

# Add BE root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.init_database import main as init_main

if __name__ == "__main__":
    asyncio.run(init_main())
