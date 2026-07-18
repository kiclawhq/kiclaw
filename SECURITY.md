# Security policy

KiClaw can read and mutate files supplied by the caller and can invoke the local KiCad CLI. Run it with the minimum filesystem permissions needed for the project in scope, and review snapshots/manifests before accepting a mutation.

Do not provide proprietary boards, datasheets, credentials, or API tokens in an issue. For a suspected vulnerability, contact the repository maintainers privately with a reproduction, affected version, host/KiCad version, and impact. Until a private reporting channel is configured, keep the report local and do not publish exploit details.

KiClaw intentionally reports unavailable backends and approximate statistics rather than fabricating results. Native DRC/ERC/export output and transaction evidence should be retained for any safety- or manufacturing-relevant decision.
