"""Soft-mode restore: hedef proje için YENİ bir IDE penceresi açar,
mevcut pencereye dokunmaz. Aggressive mode (mevcut pencereyi kapatma)
bilerek v1 kapsamı dışı - bkz. V2_BACKLOG.md.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path

from context_automator.ide_paths import resolve_ide_executable


@dataclass
class LaunchResult:
    launched: bool
    cli_used: str | None = None
    error: str | None = None


def launch_ide_soft(ide_type: str, working_dir: Path) -> LaunchResult:
    cli_path, tried = resolve_ide_executable(ide_type)
    if cli_path is None:
        return LaunchResult(
            launched=False,
            error=(
                f"'{ide_type}' çalıştırılabilir dosyası bulunamadı. Denenenler: "
                f"{', '.join(tried)}. Kurulum yolun farklıysa "
                f"CONTEXT_AUTOMATOR_{ide_type.upper()}_CLI ortam değişkenine "
                f"tam .cmd yolunu ata."
            ),
        )

    try:
        # shell=True: .cmd dosyaları Windows'ta subprocess.Popen ile
        # shell olmadan doğrudan çalıştırılamayabiliyor (PATHEXT/ilişkilendirme
        # subprocess'in doğrudan exec çağrısına dahil değil).
        subprocess.Popen(
            f'"{cli_path}" --new-window "{working_dir}"',
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return LaunchResult(launched=True, cli_used=cli_path)
    except Exception as e:  # noqa: BLE001
        return LaunchResult(launched=False, error=str(e))
