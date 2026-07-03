"""Git durumunu (branch, dirty, stash) güvenilir şekilde okur.

Bağımlılık: git CLI. subprocess çağrıları hata verirse exception fırlatmaz,
bunun yerine `available=False` döner - çağıran taraf (cli.py) buna göre
kullanıcıya anlamlı mesaj basar.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class GitState:
    available: bool
    branch: str | None = None
    dirty: bool = False
    stash_count: int = 0
    error: str | None = None


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        args, cwd=cwd, capture_output=True, text=True, timeout=5
    )


def capture_git_state(working_dir: Path) -> GitState:
    # Dizin yoksa git'i hiç deneme
    if not working_dir.exists():
        return GitState(available=False,
                        error=f"Dizin bulunamadı: {working_dir}")
    try:
        branch_res = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], working_dir)
    except FileNotFoundError:
        return GitState(available=False, error="git CLI bulunamadı (PATH kontrol et)")
    except subprocess.TimeoutExpired:
        return GitState(available=False, error="git komutu zaman aşımına uğradı")

    if branch_res.returncode != 0:
        return GitState(available=False, error=branch_res.stderr.strip() or
                         "bu dizin bir git deposu değil")

    branch = branch_res.stdout.strip()

    status_res = _run(["git", "status", "--porcelain"], working_dir)
    dirty = bool(status_res.stdout.strip())

    stash_res = _run(["git", "stash", "list"], working_dir)
    stash_count = len([l for l in stash_res.stdout.splitlines() if l.strip()])

    return GitState(
        available=True, branch=branch, dirty=dirty, stash_count=stash_count
    )
