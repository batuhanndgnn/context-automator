"""Tek, paylaşılan git-subprocess çalıştırıcı.

ÖNCEDEN: aynı "git komutunu subprocess ile çalıştır" mantığı 3 ayrı yerde
(mcp_server._run, capture/git_state._run, capture/session_logger._run)
birbirinden bağımsız olarak yazılmıştı ve üçü de FARKLI hata davranışı
sergiliyordu:
  - mcp_server._run    → başarısızlıkta özel bir sentinel string döndürüyordu
  - git_state._run     → GitState dataclass'ında ayrı bir `error` alanı vardı
  - session_logger._run→ herhangi bir exception'da sessizce "" döndürüyordu

Bu hem DRY ihlaliydi hem de daha kötüsü: mcp_server.py'deki `commit_wip`
action'ı git'in çıktısını ("nothing to commit", "fatal:" gibi İngilizce
sabit metinlerle) parse ederek başarı/başarısızlık kararı veriyordu --
returncode hiç kullanılmıyordu. Kullanıcının git'i başka bir dilde
kurulmuşsa (ör. Türkçe git.exe) bu string eşleşmeleri sessizce kırılır.

ARTIK: tek bir `run_git()` fonksiyonu var, `GitResult` (returncode, stdout,
stderr, timed_out, exc) döndürüyor. Başarı kontrolü HER ZAMAN returncode
üzerinden yapılır -- dil/locale bağımsız, çıktı metnine güvenmez.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class GitResult:
    returncode: int | None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    exc: str | None = None

    @property
    def ok(self) -> bool:
        """Komut gerçekten (returncode == 0) başarılı mıydı?

        Metin içeriğine değil, sadece process exit code'una bakar --
        locale/dil bağımsızdır.
        """
        return self.returncode == 0

    @property
    def output(self) -> str:
        """Geriye dönük uyumluluk: eski `_run()` çağıranlarının beklediği
        gibi tek bir string -- başarılıysa stdout, değilse stderr."""
        if self.timed_out or self.exc:
            return ""
        return self.stdout if self.ok else self.stderr


def run_git(
    args: list[str],
    cwd: Path,
    timeout: int = 10,
    retries: int = 1,
    retry_delay: float = 1.0,
) -> GitResult:
    """Bir git komutunu çalıştırır ve returncode'a dayalı bir sonuç döner.

    - stdin her zaman DEVNULL'a bağlanır (GPG/parola isteyen komutların
      asılı kalmasını önlemek için).
    - Zaman aşımında `retries` kez daha denenir (git'in kısa süreli kilit
      dosyası çakışmalarını tolere etmek için), aralarda `retry_delay` bekler.
    - Dizin yoksa git'i hiç denemez.
    """
    import time as _time

    if not cwd.exists():
        return GitResult(returncode=None, exc=f"Dizin bulunamadı: {cwd}")

    last_exc: str | None = None
    for attempt in range(retries + 1):
        try:
            r = subprocess.run(
                args, cwd=cwd, capture_output=True, text=True,
                timeout=timeout, stdin=subprocess.DEVNULL,
            )
            return GitResult(
                returncode=r.returncode,
                stdout=r.stdout.strip(),
                stderr=r.stderr.strip(),
            )
        except subprocess.TimeoutExpired:
            last_exc = f"zaman aşımı ({timeout}s): {' '.join(args)}"
            if attempt < retries:
                _time.sleep(retry_delay)
                continue
            return GitResult(returncode=None, timed_out=True, exc=last_exc)
        except FileNotFoundError:
            return GitResult(returncode=None, exc="git CLI bulunamadı (PATH kontrol et)")
        except Exception as e:  # noqa: BLE001
            return GitResult(returncode=None, exc=str(e))

    return GitResult(returncode=None, exc=last_exc)
