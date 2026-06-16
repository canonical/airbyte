# Copyright (c) 2026 Airbyte, Inc., all rights reserved.

"""Make `components.py` importable as the bare module name `components`,
mirroring how the runtime container resolves it."""

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
