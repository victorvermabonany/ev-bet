"""Regenerate the city index by hand.

The app builds this automatically at boot when the file is missing, so this is
only needed to inspect the output or to pre-seed the file:

    python scripts/build_place_index.py [path]
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from astrology.place_index import build  # noqa: E402
from astrology.places import INDEX_PATH  # noqa: E402

if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else INDEX_PATH)
