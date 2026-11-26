# Copyright (c) 2026 Airbyte, Inc., all rights reserved.

"""Let the tests load the manifest's custom classes.

The manifest names them `source_declarative_manifest.components.<Class>`,
because the connector image copies `components.py` into the
`source_declarative_manifest` package. That package doesn't exist here, so
`components.py` is registered under that name too. The tests can also
import it directly as `components`."""

import sys
import types
from pathlib import Path


CONNECTOR_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CONNECTOR_DIR))

import components  # noqa: E402


package = sys.modules.setdefault("source_declarative_manifest", types.ModuleType("source_declarative_manifest"))
package.components = components
sys.modules["source_declarative_manifest.components"] = components
