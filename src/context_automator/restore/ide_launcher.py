"""Soft-mode restore: hedef proje için YENİ bir IDE penceresi açar,
mevcut pencereye dokunmaz. Aggressive mode (mevcut pencereyi kapatma)
bilerek v1 kapsamı dışı - bkz. V2_BACKLOG.md.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path

from context_automator.ide_paths import resolve_ide_executable

# cmd.exe için tehlikeli olan karakterler — bunlar tırnak içinde bile
# cmd.exe tarafından özel işlenebiliyor (özellikle %). Windows dosya yolları
# zaten " karakterini barındıramaz, ama savunma amaçlı burada da reddediyoruz.
_SHELL_METACHARACTERS = set('"&|^<>%')


class UnsafePathError(ValueError):
    """working_dir veya cli_path shell metakarakteri içeriyor."""


@dataclass
class LaunchResult:
    launched: bool
    cli_used: str | None = None
    error: str | None = None


def _assert_safe_for_shell(value: str, label: str) -> None:
    bad = _SHELL_METACHARACTERS.intersection(value)
    if bad:
        raise UnsafePathError(
            f"{label} güvensiz karakter(ler) içeriyor ({''.join(sorted(bad))}): {value}"
        )


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
        # subprocess'in doğrudan exec çağrısına dahil değil). Bu yüzden path'ler
        # ham bir string'e gömülüyor — shell=True + f-string kombinasyonu
        # potansiyel bir komut enjeksiyonu yüzeyi, o yüzden gömmeden önce
        # doğruluyoruz.
        _assert_safe_for_shell(str(cli_path), "IDE çalıştırılabilir yolu")
        _assert_safe_for_shell(str(working_dir), "working_dir")

        subprocess.Popen(
            f'"{cli_path}" --new-window "{working_dir}"',
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return LaunchResult(launched=True, cli_used=cli_path)
    except UnsafePathError as e:
        return LaunchResult(launched=False, error=str(e))
    except Exception as e:  # noqa: BLE001
        return LaunchResult(launched=False, error=str(e))
