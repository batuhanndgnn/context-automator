"""Kaydedilmiş açık dosyaları, kayıtlı satır/sütun konumlarında yeniden açar.

BİLİNEN SINIRLAMA: IDE penceresinin "hazır" olduğunu garanti eden bir
mekanizma yok (process lifecycle / readiness check Faz 4'te ele alınacak).
Şu an launch_ide_soft() ile dosya açma arasında sabit bir bekleme (caller
tarafında, cli.py'deki --wait-seconds) kullanılıyor - bu MVP için yeterli
ama production-grade değil, bilerek böyle bırakıldı.
"""

import subprocess
from dataclasses import dataclass

from context_automator.ide_paths import resolve_ide_executable


@dataclass
class ReopenResult:
    file: str
    ok: bool
    error: str | None = None


def reopen_files(ide_type: str, cursor_positions: list[dict]) -> list[ReopenResult]:
    cli_path, tried = resolve_ide_executable(ide_type)
    if cli_path is None:
        err = f"'{ide_type}' bulunamadı (denenenler: {', '.join(tried)})"
        return [ReopenResult(file=p.get("file", "?"), ok=False, error=err)
                for p in cursor_positions]

    results: list[ReopenResult] = []
    for pos in cursor_positions:
        file_path = pos.get("file")
        line = pos.get("line") or 1
        col = pos.get("col") or 1
        if not file_path:
            continue
        try:
            # `-g path:line:column` aynı pencerede dosyayı belirtilen
            # konuma giderek açar (--new-window vermiyoruz, var olan
            # pencereyi kullanır).
            subprocess.run(
                f'"{cli_path}" -g "{file_path}:{line}:{col}"',
                shell=True, capture_output=True, text=True, timeout=10,
            )
            results.append(ReopenResult(file=file_path, ok=True))
        except Exception as e:  # noqa: BLE001
            results.append(ReopenResult(file=file_path, ok=False, error=str(e)))

    return results
