"""IDE CLI yürütülebilirini bulur.

Öncelik sırası: env var override → PATH → bilinen kurulum yolları.
Cursor ve VS Code eşit öncelikte — hangisi kuruluysa çalışır.

Üç platform da destekleniyor (Windows/macOS/Linux). PATH araması
(shutil.which) zaten cross-platform çalışır -- çoğu Mac/Linux kurulumunda
`code`/`cursor` komutu PATH'e sembolik link olarak eklendiği için bu adım
tek başına yeterli olur. Bilinen-yol fallback'i, PATH'e eklenmemiş
kurulumlar için platforma özel tipik konumları dener.
"""

import os
import shutil
import sys
from pathlib import Path

from context_automator.config import settings

_ENV_OVERRIDES = {
    "cursor": "CONTEXT_AUTOMATOR_CURSOR_CLI",
    "vscode": "CONTEXT_AUTOMATOR_VSCODE_CLI",
}

_CLI_NAMES = {"cursor": "cursor", "vscode": "code"}


def _candidates(ide_type: str) -> list[Path]:
    paths: list[Path] = []

    if os.name == "nt":
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

    elif sys.platform == "darwin":
        if ide_type == "cursor":
            paths.append(Path("/Applications/Cursor.app/Contents/Resources/app/bin/cursor"))
            paths.append(Path.home() / "Applications" / "Cursor.app" / "Contents" / "Resources" / "app" / "bin" / "cursor")
        if ide_type == "vscode":
            paths.append(Path("/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code"))
            paths.append(Path.home() / "Applications" / "Visual Studio Code.app" / "Contents" / "Resources" / "app" / "bin" / "code")

    else:
        # Linux -- yaygın paket yöneticisi/snap/AppImage konumları.
        if ide_type == "cursor":
            paths += [
                Path("/usr/bin/cursor"),
                Path("/usr/share/cursor/cursor"),
                Path("/snap/bin/cursor"),
                Path.home() / ".local" / "share" / "cursor" / "cursor",
                Path.home() / "Applications" / "cursor.AppImage",
            ]
        if ide_type == "vscode":
            paths += [
                Path("/usr/bin/code"),
                Path("/usr/share/code/bin/code"),
                Path("/snap/bin/code"),
                Path.home() / ".local" / "share" / "code" / "bin" / "code",
            ]

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

    # 2. PATH -- cross-platform: Windows/macOS/Linux'ta `code`/`cursor`
    # kurulumla birlikte PATH'e eklendiyse bu adım tek başına yeterli olur.
    cli = _CLI_NAMES.get(ide_type)
    if cli:
        tried.append(f"PATH → {cli}")
        found = shutil.which(cli)
        if found:
            return found, tried

    # 3. Bilinen kurulum yolları (platforma göre)
    for p in _candidates(ide_type):
        tried.append(str(p))
        if p.exists():
            return str(p), tried

    return None, tried
