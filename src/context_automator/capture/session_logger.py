"""AI Session Logger — Faz 7 + Faz 8 (MCP Sampling) implementasyonu.

save_context çağrıldığında:
  1. git diff + git log → ham değişiklik verisi toplanır
  2. Özet üretilir — iki yoldan biriyle:
     a) MCP Sampling (öncelikli): sunucu kendi API key'ini kullanmaz,
        "bana bir mesaj üret" isteğini MCP session üzerinden Claude
        Desktop'a yollar. Maliyet ve model seçimi tamamen Desktop
        tarafındaki ayarlarda kalır.
     b) BYOK / httpx fallback: sampling client tarafından desteklenmiyorsa
        (veya CLI'den, MCP session'ı olmadan çalıştırılıyorsa) ve
        ANTHROPIC_API_KEY tanımlıysa doğrudan Anthropic API'ye gidilir.
  3. "Bu seansta ne yapıldı" özeti SQLite'a yazılır

switch_context çağrıldığında:
  4. Önceki özet okunur → Claude kullanıcıyı karşılar

Ne sampling ne de API key mevcutsa sessizce atlanır, araç yine de çalışır.
"""

import json
import os
import subprocess
from pathlib import Path

import httpx
from dotenv import load_dotenv

from context_automator.util import logger

load_dotenv()

# Not: Önceden burada `from venv import logger` vardı — Python'un venv
# modülünün dahili logger'ını import ediyordu (yanlışlıkla, muhtemelen
# otomatik tamamlama hatası). Sonuç: bu dosyadaki hatalar app.log'a hiç
# düşmüyordu, ayrı ve konfigüre edilmemiş bir logger'a gidiyordu. Artık
# projenin kendi paylaşılan logger'ı (util.py) kullanılıyor.

DEFAULT_MODEL = "claude-haiku-4-5-20251001"


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


def _build_prompt(session_data: dict) -> str:
    return f"""Aşağıdaki git verisini analiz et. Bu bir yazılım geliştirici stajyerin 
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


async def generate_session_summary_via_sampling(session_data: dict, mcp_session) -> str | None:
    """MCP Sampling ile özet üretir — sunucu kendi API key'ini kullanmaz.

    `mcp_session` bir `mcp.server.session.ServerSession`'dır (mcp_server.py
    içinde `app.request_context.session` ile elde edilir). İstek, "bana bir
    mesaj üret" olarak MCP client'a (Claude Desktop) yollanır; hangi model
    kullanılacağına ve maliyetine client tarafı karar verir.

    Client sampling desteklemiyorsa veya istek başarısız olursa None döner
    (çağıran taraf BYOK fallback'e düşer).
    """
    try:
        from mcp import types as mcp_types
    except ImportError:
        logger.warning("mcp.types import edilemedi, sampling atlanıyor.")
        return None

    if mcp_session is None:
        return None

    if not mcp_session.check_client_capability(
        mcp_types.ClientCapabilities(sampling=mcp_types.SamplingCapability())
    ):
        logger.info("Client sampling'i desteklemiyor, BYOK fallback'e düşülüyor.")
        return None

    prompt = _build_prompt(session_data)
    try:
        result = await mcp_session.create_message(
            messages=[
                mcp_types.SamplingMessage(
                    role="user",
                    content=mcp_types.TextContent(type="text", text=prompt),
                )
            ],
            max_tokens=300,
        )
        content = result.content
        if isinstance(content, mcp_types.TextContent):
            return content.text.strip()
        return str(content).strip()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"MCP sampling isteği başarısız oldu: {e}")
        return None


def generate_session_summary_via_api(session_data: dict) -> str | None:
    """BYOK fallback: doğrudan Anthropic API'ye gönderir, özet döner.

    ANTHROPIC_API_KEY env var yoksa None döner (sessizce atlanır).
    Sadece sampling mevcut olmadığında (ör. CLI'den çalıştırılırken, MCP
    session'ı yokken) ya da client sampling desteklemediğinde kullanılır.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    prompt = _build_prompt(session_data)

    try:
        response = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": DEFAULT_MODEL,
                "max_tokens": 300,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=15,
        )
        if response.status_code == 200:
            data = response.json()
            return data["content"][0]["text"].strip()
        logger.warning(f"Claude API {response.status_code} döndü: {response.text[:200]}")
        return None
    except Exception as e:
        logger.error(f"Claude API çağrısı sırasında hata oluştu: {str(e)}")
        return None


async def save_session_summary(conn, context_id: int, working_dir: Path,
                                mcp_session=None) -> str | None:
    """Session datasını topla, AI özet üret, DB'ye yaz.

    Öncelik: MCP Sampling (mcp_session verilmişse ve client destekliyorsa) →
    başarısızsa BYOK (ANTHROPIC_API_KEY) → o da yoksa None.

    Döner: üretilen özet string veya None.
    """
    session_data = gather_session_data(working_dir)

    summary = await generate_session_summary_via_sampling(session_data, mcp_session)
    if not summary:
        summary = generate_session_summary_via_api(session_data)

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
