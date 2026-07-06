"""IDE CLI yürütülebilirini bulur.

Öncelik sırası: env var override → PATH → bilinen kurulum yolları.
Cursor ve VS Code eşit öncelikte — hangisi kuruluysa çalışır.
İşletim sistemine (Windows/macOS/Linux) göre dinamik yol ve komut üretir.
"""

import os
import shutil
import platform
from pathlib import Path

from context_automator.config import settings

_ENV_OVERRIDES = {
    "cursor": "CONTEXT_AUTOMATOR_CURSOR_CLI",
    "vscode": "CONTEXT_AUTOMATOR_VSCODE_CLI",
}

# İşletim sistemini tespit edip komutları (CLI_NAMES) dinamik belirliyoruz
_OS = platform.system()
_IS_WINDOWS = _OS == "Windows"
_IS_MAC = _OS == "Darwin"

if _IS_WINDOWS:
    _CLI_NAMES = {"cursor": "cursor.cmd", "vscode": "code.cmd"}
else:
    _CLI_NAMES = {"cursor": "cursor", "vscode": "code"}


def _candidates(ide_type: str) -> list[Path]:
    paths: list[Path] = []

    if _IS_WINDOWS:
        local = os.environ.get("LOCALAPPDATA", "")
        pf    = os.environ.get("PROGRAMFILES", "")
        pf86  = os.environ.get("PROGRAMFILES(X86)", "")

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
                
    elif _IS_MAC:
        if ide_type == "cursor":
            paths.append(Path("/Applications/Cursor.app/Contents/MacOS/Cursor"))
        elif ide_type == "vscode":
            paths.append(Path("/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code"))
            
    else: 
        # Linux (Genelde PATH'te olurlar, ek özel yollar buraya eklenebilir)
        pass

    return paths


def resolve_ide_executable(ide_type: str) -> tuple[str | None, list[str]]:
    """(yol, denenenler) döner. Bulunamazsa yol=None."""
    tried: list[str] = []

    # 1. env var override 
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