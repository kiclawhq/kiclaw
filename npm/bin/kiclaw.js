#!/usr/bin/env node

import { spawnSync } from "node:child_process";

const args = process.argv.slice(2);
const python = process.env.KICLAW_PYTHON || "python3";

function run(command, commandArgs) {
  const result = spawnSync(command, commandArgs, { stdio: "inherit" });
  if (result.error?.code === "ENOENT") return false;
  process.exit(result.status ?? 1);
}

// `uvx` makes `npx kiclaw serve` resolve the published PyPI server. Set
// KICLAW_LOCAL=1 while developing to use the checked-out Python project.
if (process.env.KICLAW_LOCAL === "1") {
  run("uv", ["run", "--no-editable", "kiclaw", ...args]);
}

if (!run("uvx", ["--from", "kiclaw", "kiclaw", ...args])) {
  run(python, ["-m", "kiclaw", ...args]);
}
