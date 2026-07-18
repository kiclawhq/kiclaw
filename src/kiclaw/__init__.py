"""KiClaw: reliable KiCad MCP primitives.

KiClaw does not load third-party Pydantic plugins.  Opting out before MCP or
Pydantic is imported keeps CLI/MCP startup deterministic on hosts with many
installed distributions (Pydantic otherwise scans every distribution's entry
points during model construction).
"""

import os

os.environ.setdefault("PYDANTIC_DISABLE_PLUGINS", "1")

__version__ = "0.1.0"
