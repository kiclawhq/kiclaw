# kiclaw (npm launcher)

This package provides the npm entry point for the KiClaw Python MCP server.
It lets an MCP client launch the published PyPI package with `npx kiclaw serve`.

## Usage

```bash
npx -y kiclaw doctor
npx -y kiclaw serve
```

The launcher uses `uvx --from kiclaw` when `uv` is installed and falls back to
`python3 -m kiclaw`. For local repository development, use `KICLAW_LOCAL=1`.

Configure an MCP client with:

```json
{
  "mcpServers": {
    "kiclaw": {
      "command": "npx",
      "args": ["-y", "kiclaw", "serve"]
    }
  }
}
```

KiCad itself remains a host prerequisite. The npm package is a launcher, not a
replacement for KiCad or the Python server runtime.
