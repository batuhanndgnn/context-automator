"""IDE CLI yürütülebilirini bulur.

Öncelik sırası: env var override → PATH → bilinen kurulum yolları.
Cursor ve VS Code eşit öncelikte — hangisi kuruluysa çalışır.
"""

import os
import shutil
from pathlib import Path

from context_automator.config import settings

_ENV_OVERRIDES = {
    "cursor": "CONTEXT_AUTOMATOR_CURSOR_CLI",
    "vscode": "CONTEXT_AUTOMATOR_VSCODE_CLI",
}

_CLI_NAMES = {"cursor": "cursor", "vscode": "code"}


def _candidates(ide_type: str) -> list[Path]:
    local = os.environ.get("LOCALAPPDATA", "")
    pf    = os.environ.get("PROGRAMFILES", "")
    pf86  = os.environ.get("PROGRAMFILES(X86)", "")

    paths: list[Path] = []

    if ide_type == "cursor" and local:
        paths += [
            Path(local) / "Programs" / "cursor" / "resources" / "app" / "bin" / "cursor.cmd",
            Path(local) / "Programs" / "Cursor" / "resources" / "app" / "bin" / "cursor.cmd",
        ]

    if ide_type == "vscode":
        if local:
            paths.append(Path(local) / "Programs" / "Microsoft VS Code" / "bin" / "code.cmd")
        if pf:
            paths.append(Path(pf) / "Microsoft VS Code" / "bin" / "code.cmd")
        if pf86:
            paths.append(Path(pf86) / "Microsoft VS Code" / "bin" / "code.cmd")

    return paths


def resolve_ide_executable(ide_type: str) -> tuple[str | None, list[str]]:
    """(yol, denenenler) döner. Bulunamazsa yol=None."""
    tried: list[str] = []

    # 1. env var override (artık merkezi Settings üzerinden -- ama doğrudan
    # os.environ'da manuel export edilmiş bir değer varsa da yakalıyoruz,
    # geriye dönük uyumluluk için)
    env_key = _ENV_OVERRIDES.get(ide_type)
    if env_key:
        override = settings.cli_override_for(ide_type) or os.environ.get(env_key)
        if override:
            tried.append(f"env {env_key}={override}")
            if Path(override).exists():
                return override, tried

    # 2. PATH
    cli = _CLI_NAMES.get(ide_type)
    if cli:
        tried.append(f"PATH → {cli}")
        found = shutil.which(cli)
        if found:
            return found, tried

    # 3. Bilinen kurulum yolları
    for p in _candidates(ide_type):
        tried.append(str(p))
        if p.exists():
            return str(p), tried

    return None, tried
