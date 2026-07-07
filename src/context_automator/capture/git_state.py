"""Git durumunu (branch, dirty, stash) güvenilir şekilde okur.

Bağımlılık: git CLI. Hata olursa exception fırlatmaz, bunun yerine
`available=False` döner - çağıran taraf (cli.py, mcp_server.py) buna göre
kullanıcıya anlamlı mesaj basar.

NOT: Kendi subprocess mantığını yazmak yerine artık paylaşılan
`gitutil.run_git()` kullanılıyor (bkz. gitutil.py docstring'i) -- önceden
bu dosyanın, mcp_server.py'nin ve session_logger.py'nin her biri git
komutlarını çalıştırmak için kendi (ve birbirinden farklı davranan)
_run() fonksiyonlarını yazmıştı.
"""

from dataclasses import dataclass
from pathlib import Path

from context_automator.gitutil import run_git


@dataclass
class GitState:
    available: bool
    branch: str | None = None
    dirty: bool = False
    stash_count: int = 0
    error: str | None = None


def capture_git_state(working_dir: Path) -> GitState:
    # Dizin yoksa git'i hiç deneme
    if not working_dir.exists():
        return GitState(available=False,
                        error=f"Dizin bulunamadı: {working_dir}")

    branch_res = run_git(["git", "rev-parse", "--abbrev-ref", "HEAD"], working_dir)

    if branch_res.exc:
        return GitState(available=False, error=branch_res.exc)
    if not branch_res.ok:
        return GitState(available=False, error=branch_res.stderr or
                         "bu dizin bir git deposu değil")

    branch = branch_res.stdout

    status_res = run_git(["git", "status", "--porcelain"], working_dir)
    if not status_res.ok:
        return GitState(available=False, error=status_res.exc or status_res.stderr)
    dirty = bool(status_res.stdout.strip())

    stash_res = run_git(["git", "stash", "list"], working_dir)
    if not stash_res.ok:
        return GitState(available=False, error=stash_res.exc or stash_res.stderr)
    stash_count = len([l for l in stash_res.stdout.splitlines() if l.strip()])

    return GitState(
        available=True, branch=branch, dirty=dirty, stash_count=stash_count
    )
