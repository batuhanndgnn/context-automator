"""AI Session Logger — Faz 7 implementasyonu.

save_context çağrıldığında:
  1. git diff + git log → ham değişiklik verisi toplanır
  2. Claude API'ye gönderilir (claude-haiku-4-5, hızlı ve ucuz)
  3. "Bu seansta ne yapıldı" özeti SQLite'a yazılır

switch_context çağrıldığında:
  4. Önceki özet okunur → Claude kullanıcıyı karşılar

API key yoksa sessizce atlanır, araç yine de çalışır.
"""

import json
import os
import subprocess
from pathlib import Path
from venv import logger

import httpx
from dotenv import load_dotenv
load_dotenv()

def _run(cmd: list[str], cwd: Path, timeout: int = 10) -> str:
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True,
                           text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def gather_session_data(working_dir: Path) -> dict:
    """Git'ten bu seanstaki değişiklikleri toplar."""
    diff = _run(["git", "diff", "HEAD"], working_dir)
    if not diff:
        diff = _run(["git", "diff"], working_dir)

    log = _run(["git", "log", "--oneline", "-10",
                "--pretty=format:%h %s (%ar)"], working_dir)

    changed_files = _run(["git", "diff", "--name-only", "HEAD"], working_dir)
    if not changed_files:
        changed_files = _run(["git", "diff", "--name-only"], working_dir)

    status = _run(["git", "status", "--short"], working_dir)

    return {
        "working_dir": str(working_dir),
        "git_log": log[:2000] if log else "(commit yok)",
        "changed_files": changed_files[:500] if changed_files else "(değişiklik yok)",
        "git_diff_preview": diff[:3000] if diff else "(diff boş)",
        "git_status": status[:500] if status else "",
    }


def generate_session_summary(session_data: dict) -> str | None:
    """Claude API'ye session verisini gönderir, özet döner.

    ANTHROPIC_API_KEY env var yoksa None döner (sessizce atlanır).
    Model: "claude-3-haiku-20240307" — en hızlı, session summary için ideal.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    prompt = f"""Aşağıdaki git verisini analiz et. Bu bir yazılım geliştirici stajyerin 
bir proje üzerindeki çalışma seansının verisi. 

Proje dizini: {session_data['working_dir']}

Son commitler:
{session_data['git_log']}

Değişen dosyalar:
{session_data['changed_files']}

Git diff önizlemesi:
{session_data['git_diff_preview']}

Görev: Bu seansta ne yapıldığını 2-4 cümleyle, Türkçe, teknik ama anlaşılır bir dille özetle.
Gereksiz giriş/çıkış cümlesi KULLANMA. Doğrudan özeti yaz.
Değişiklik yoksa "Bu seansta commit edilmiş değişiklik bulunamadı." yaz."""

    try:
        response = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-3-haiku-20240307",
                "max_tokens": 300,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=15,
        )
        if response.status_code == 200:
            data = response.json()
            return data["content"][0]["text"].strip()
    except Exception as e:
        logger.error(f"Claude API çağrısı sırasında hata oluştu: {str(e)}")
        return None


def save_session_summary(conn, context_id: int, working_dir: Path) -> str | None:
    """Session datasını topla, AI özet üret, DB'ye yaz.

    Döner: üretilen özet string veya None (API key yok / hata).
    """
    session_data = gather_session_data(working_dir)
    summary = generate_session_summary(session_data)
    if summary:
        conn.execute(
            "UPDATE contexts SET session_summary = ? WHERE id = ?",
            (summary, context_id),
        )
        conn.commit()
    return summary


def build_welcome_message(row: dict, live_branch: str | None,
                           live_dirty: bool) -> str:
    """switch_context sonrası Claude'un kullanıcıyı karşılayacağı bağlam metnini üretir.

    Bu metin doğrudan MCP tool yanıtına eklenir;
    Claude Desktop bunu okuyunca doğal bir karşılama mesajı oluşturur.
    """
    lines = []

    summary = row.get("session_summary")
    if summary:
        lines.append(f"SON SEANS ÖZETİ:\n{summary}")
    else:
        lines.append("(Bu proje için henüz seans özeti yok — "
                     "bir sonraki save'de AI otomatik üretecek.)")

    if row.get("active_files"):
        files = json.loads(row["active_files"])
        if files:
            file_list = "\n".join(f"  • {f}" for f in files[:5])
            lines.append(f"\nSON AÇIK DOSYALAR ({len(files)} adet):\n{file_list}")

    lines.append(f"\nGIT DURUMU:\n"
                 f"  Kayıtlı branch : {row.get('git_branch', '?')}\n"
                 f"  Şu an          : {live_branch or '?'}\n"
                 f"  Uncommitted    : {'⚠️  Evet' if live_dirty else '✅ Temiz'}")

    if row.get("updated_at"):
        lines.append(f"\nSon güncelleme: {row['updated_at'][:10]}")

    return "\n".join(lines)
