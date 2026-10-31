"""Provider API keys: which are set, and saving them to the backend's .env.

The Control Panel (through /config/keys, local clients only) and
``crucible keys`` both use these. Keys are written to the untracked .env and
to the running process's environment, never anywhere else.
"""

import os
import re
from typing import Dict, Mapping, MutableMapping, Optional

from app.registry import provider_env_keys

ENV_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

# Every family's key, so a new provider family needs no edit here.
KEY_NAMES = provider_env_keys()

# Printable ASCII without quotes, backslashes or whitespace. Real provider keys
# fit this; anything else could break out of the quoted .env value.
_VALID_VALUE = re.compile(r'^[\x21-\x7e]+$')
_FORBIDDEN_CHARS = set('"\'\\`$')


def mask(value: str) -> str:
    if len(value) <= 8:
        return "•" * len(value)
    return "•" * (len(value) - 4) + value[-4:]


def key_status(environ: Mapping[str, str] = os.environ) -> Dict[str, Dict[str, object]]:
    """{name: {set, masked}} for every provider key; never the values."""
    status = {}
    for name in sorted(KEY_NAMES):
        value = environ.get(name) or ""
        status[name] = {"set": bool(value), "masked": mask(value) if value else ""}
    return status


def check_names(names) -> None:
    """Raises ValueError unless every name is a provider key."""
    unknown = set(names) - KEY_NAMES
    if unknown:
        raise ValueError(f"Unknown keys: {unknown}")


def save_keys(
    keys: Mapping[str, str],
    env_path: Optional[str] = None,
    environ: MutableMapping[str, str] = os.environ,
) -> None:
    """Set (or, with an empty value, remove) keys in .env and the environment.

    Raises ValueError for a name that isn't a provider key or a value that
    could add lines to .env."""
    check_names(keys)

    cleaned: Dict[str, str] = {}
    for name, value in keys.items():
        value = value.strip()
        if value and (not _VALID_VALUE.match(value) or _FORBIDDEN_CHARS & set(value)):
            raise ValueError(f"{name} contains characters an API key cannot have")
        cleaned[name] = value

    env_path = env_path or ENV_PATH
    lines: list[str] = []
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            lines = f.readlines()

    for name, value in cleaned.items():
        found = False
        for i, line in enumerate(lines):
            if re.match(rf"^\s*{re.escape(name)}\s*=", line):
                lines[i] = f'{name}="{value}"\n' if value else ""
                found = True
                break
        if not found and value:
            lines.append(f'{name}="{value}"\n')

    with open(env_path, "w") as f:
        f.writelines(line for line in lines if line)
    try:
        os.chmod(env_path, 0o600)
    except OSError:
        pass

    for name, value in cleaned.items():
        if value:
            environ[name] = value
        elif name in environ:
            del environ[name]
