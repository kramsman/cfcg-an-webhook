"""
Compare environment variables between set-env-vars.sh (Cloud Run / deploy)
and .env (local development) and print any differences.

Run from the project root:
    python compare_configs.py
"""

import re
from pathlib import Path


def _strip_inline_comment(value: str) -> str:
    """Remove trailing '  # comment' from a value string."""
    # Split on ' #' and keep only the part before it
    parts = re.split(r'\s+#\s', value, maxsplit=1)
    return parts[0].strip()


def parse_sh(path: Path) -> dict:
    """Parse ENV_VARS array entries from set-env-vars.sh.

    Handles lines like:
        "KEY=value"           # comment
        "KEY="                # empty value
    Skips comment-only lines and commented-out entries (lines starting with #).
    """
    result = {}
    in_block = False
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if stripped == 'ENV_VARS=(':
            in_block = True
            continue
        if in_block and stripped == ')':
            break
        if not in_block:
            continue
        # Skip blank lines and comment-only lines (including commented-out entries like #  "KEY=...")
        if not stripped or stripped.startswith('#'):
            continue
        # Extract the quoted "KEY=value" part — the value ends at the closing quote
        m = re.match(r'^"([^"]*)"', stripped)
        if not m:
            continue
        kv = m.group(1)                         # KEY=value (no inline comment)
        if '=' not in kv:
            continue
        key, _, value = kv.partition('=')
        result[key.strip()] = value.strip()

    return result


def parse_env(path: Path) -> dict:
    """Parse KEY=value pairs from .env.

    Skips blank lines, comment lines, and commented-out variables.
    Strips inline comments from values.
    """
    result = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' not in line:
            continue
        key, _, value = line.partition('=')
        result[key.strip()] = _strip_inline_comment(value)
    return result


def compare(sh_vars: dict, env_vars: dict):
    all_keys = sorted(sh_vars.keys() | env_vars.keys())

    only_sh  = [k for k in all_keys if k in sh_vars and k not in env_vars]
    only_env = [k for k in all_keys if k in env_vars and k not in sh_vars]
    differ   = [k for k in all_keys if k in sh_vars and k in env_vars and sh_vars[k] != env_vars[k]]
    same     = [k for k in all_keys if k in sh_vars and k in env_vars and sh_vars[k] == env_vars[k]]

    print(f"\n{'='*60}")
    print("Config comparison: set-env-vars.sh  vs  .env")
    print(f"{'='*60}\n")

    if differ:
        print(f"DIFFERENT VALUES ({len(differ)}):")
        for k in differ:
            print(f"  {k}")
            print(f"    deploy (sh):  {sh_vars[k]!r}")
            print(f"    local  (.env): {env_vars[k]!r}")
        print()
    else:
        print("No value differences.\n")

    if only_sh:
        print(f"ONLY IN set-env-vars.sh ({len(only_sh)}):")
        for k in only_sh:
            print(f"  {k} = {sh_vars[k]!r}")
        print()

    if only_env:
        print(f"ONLY IN .env ({len(only_env)}):")
        for k in only_env:
            print(f"  {k} = {env_vars[k]!r}")
        print()

    print(f"Matching: {len(same)}  |  Different: {len(differ)}  |  Only in sh: {len(only_sh)}  |  Only in .env: {len(only_env)}")
    print()


if __name__ == "__main__":
    root = Path(__file__).parent
    sh_vars  = parse_sh(root / "set-env-vars.sh")
    env_vars = parse_env(root / ".env")
    compare(sh_vars, env_vars)
