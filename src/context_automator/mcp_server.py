"""Context-Automator MCP Server — Faz 5 + 6 + 7

stdio transport. Claude Desktop veya VS Code + MCP extension üzerinden çalışır.

TOOLS (5 temel + 1 agentic):
  save_context, switch_context, list_contexts, preview_context,
  delete_context, resolve_git_state

RESOURCES (Faz 5 - dinamik bağlam):
  context://current-project-spec   → aktif projenin README + dizin ağacı
  context://current-git-status     → anlık git diff + log
  context://session-history/{name} → geçmiş seans özeti

Başlatma:
  .venv/Scripts/python.exe -m context_automator.mcp_server
"""

import json
import os
import subprocess
import time
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

from context_automator.util import (
    build_snapshot, upsert_context, get_db, log_event, now_iso,
)
from context_automator.capture.git_state import capture_git_state
from context_automator.capture.session_logger import (
    save_session_summary, build_welcome_message,
)
from context_automator.restore.ide_launcher import launch_ide_soft
from context_automator.restore.file_restorer import reopen_files

app = Server("context-automator")

# Hangi dizin "aktif proje" sayılır — switch_context günceller
_current_project_dir: Path | None = None


def _ok(data: dict) -> list[types.TextContent]:
    return [types.TextContent(type="text",
                               text=json.dumps(data, ensure_ascii=False, indent=2))]


def _err(msg: str, code: str = "error") -> list[types.TextContent]:
    return [types.TextContent(type="text",
                               text=json.dumps({"status": code, "error": msg},
                                               ensure_ascii=False))]


def _run(cmd: list[str], cwd: Path) -> str:
    try:
        if not cwd.exists():
            return f"(dizin bulunamadı: {cwd})"
        r = subprocess.run(cmd, cwd=cwd, capture_output=True,
                           text=True, timeout=5)
        return r.stdout.strip()
    except subprocess.TimeoutExpired:
        return "(git komutu zaman aşımı)"
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# FAZ 5 — MCP Resources
# ---------------------------------------------------------------------------

@app.list_resources()
async def list_resources() -> list[types.Resource]:
    resources = [
        types.Resource(
            uri="context://current-project-spec",
            name="Aktif Proje Spesifikasyonu",
            description="Şu an çalışılan projenin README ve dizin yapısı. "
                        "Claude bu kaynağı okuyarak projeyi otomatik anlar.",
            mimeType="text/plain",
        ),
        types.Resource(
            uri="context://current-git-status",
            name="Anlık Git Durumu",
            description="Aktif projenin canlı git diff, log ve status bilgisi.",
            mimeType="text/plain",
        ),
    ]

    # Kayıtlı her context için session-history resource'u ekle
    conn = get_db()
    try:
        rows = conn.execute("SELECT name FROM contexts").fetchall()
        for row in rows:
            resources.append(types.Resource(
                uri=f"context://session-history/{row['name']}",
                name=f"Seans Geçmişi — {row['name']}",
                description=f"'{row['name']}' projesinin önceki seans özeti ve git bilgisi.",
                mimeType="text/plain",
            ))
    finally:
        conn.close()

    return resources


@app.read_resource()
async def read_resource(uri: str) -> str:
    global _current_project_dir
    cwd = _current_project_dir or Path.cwd()

    # context://current-project-spec
    if uri == "context://current-project-spec":
        lines = [f"# Proje: {cwd.name}", f"Dizin: {cwd}", ""]

        readme_path = cwd / "README.md"
        if readme_path.exists():
            content = readme_path.read_text(encoding="utf-8", errors="replace")
            lines.append("## README.md")
            lines.append(content[:3000])
        else:
            lines.append("(README.md bulunamadı)")

        lines.append("\n## Dizin Yapısı")
        try:
            for p in sorted(cwd.rglob("*")):
                if any(skip in p.parts for skip in
                       (".git", ".venv", "__pycache__", "node_modules", ".vscode")):
                    continue
                rel = p.relative_to(cwd)
                indent = "  " * (len(rel.parts) - 1)
                icon = "📁" if p.is_dir() else "📄"
                lines.append(f"{indent}{icon} {rel.name}")
                if len(lines) > 80:
                    lines.append("  ... (daha fazlası var)")
                    break
        except Exception:
            pass

        return "\n".join(lines)

    # context://current-git-status
    if uri == "context://current-git-status":
        branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd)
        status = _run(["git", "status", "--short"], cwd)
        log    = _run(["git", "log", "--oneline", "-10",
                       "--pretty=format:%h %s (%ar)"], cwd)
        diff   = _run(["git", "diff", "HEAD"], cwd)

        return "\n".join([
            f"Branch: {branch or '(bilinmiyor)'}",
            f"\nDeğişen dosyalar:\n{status or '(temiz)'}",
            f"\nSon commitler:\n{log or '(yok)'}",
            f"\nDiff önizlemesi:\n{diff[:2000] if diff else '(diff yok)'}",
        ])

    # context://session-history/{name}
    if uri.startswith("context://session-history/"):
        ctx_name = uri.split("/", 2)[-1]
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT * FROM contexts WHERE name = ?", (ctx_name,)
            ).fetchone()
        finally:
            conn.close()

        if not row:
            return f"'{ctx_name}' adında kayıtlı context bulunamadı."

        row = dict(row)
        live = capture_git_state(Path(row["working_dir"]))
        return build_welcome_message(row, live.branch, live.dirty)

    return f"Bilinmeyen resource URI: {uri}"


# ---------------------------------------------------------------------------
# Tool tanımları
# ---------------------------------------------------------------------------

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="save_context",
            description=(
                "Aktif geliştirme ortamını snapshot olarak kaydeder ve "
                "AI ile bu seansta ne yapıldığını otomatik özetler. "
                "Proje geçişinden ÖNCE çağır."
            ),
            inputSchema={
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string",
                             "description": "Proje adı (ör. 'whatsapp-bot')"},
                    "ide":  {"type": "string", "enum": ["cursor", "vscode"]},
                    "dry_run": {"type": "boolean", "default": False},
                },
            },
        ),
        types.Tool(
            name="switch_context",
            description=(
                "Kayıtlı projeye geçer: VS Code/Cursor'ı açar, "
                "dosyaları geri yükler ve önceki seansta ne yapıldığını söyler."
            ),
            inputSchema={
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string"},
                    "dry_run": {"type": "boolean", "default": False},
                    "wait_seconds": {"type": "number", "default": 2.0},
                },
            },
        ),
        types.Tool(
            name="list_contexts",
            description="Kayıtlı tüm projeleri ve son seans özetlerini listeler.",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="preview_context",
            description="Proje detayı + canlı git uyarısı. switch öncesi çağır.",
            inputSchema={
                "type": "object",
                "required": ["name"],
                "properties": {"name": {"type": "string"}},
            },
        ),
        types.Tool(
            name="delete_context",
            description="Bir proje snapshot'ını siler.",
            inputSchema={
                "type": "object",
                "required": ["name"],
                "properties": {"name": {"type": "string"}},
            },
        ),
        types.Tool(
            name="resolve_git_state",
            description=(
                "FAZ 6 — Agentic Git: Kaydedilmemiş değişiklikler varsa "
                "ne yapılacağına karar verip uygular. "
                "action: 'stash' | 'commit_wip' | 'discard' | 'status'"
            ),
            inputSchema={
                "type": "object",
                "required": ["action"],
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["status", "stash", "commit_wip", "discard"],
                        "description": (
                            "status → durumu göster, "
                            "stash → git stash push, "
                            "commit_wip → 'WIP: [timestamp]' mesajıyla commit, "
                            "discard → git checkout -- . (DİKKAT: geri alınamaz)"
                        ),
                    },
                    "context_name": {
                        "type": "string",
                        "description": "Hangi projenin working dir'inde çalışılacak (opsiyonel, yoksa cwd)",
                    },
                },
            },
        ),
    ]


# ---------------------------------------------------------------------------
# Tool implementasyonları
# ---------------------------------------------------------------------------

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    global _current_project_dir

    # ── save_context ─────────────────────────────────────────────────────────
    if name == "save_context":
        ctx_name = arguments.get("name", "").strip()
        if not ctx_name:
            return _err("'name' boş olamaz.", "validation_error")

        ide_type = arguments.get("ide")
        dry_run  = arguments.get("dry_run", False)

        record, warnings = build_snapshot(ctx_name, ide_type)

        if dry_run:
            return _ok({"status": "dry_run", "would_save": record,
                         "warnings": warnings})

        conn = get_db()
        try:
            ctx_id = upsert_context(conn, record)
            log_event(conn, ctx_id, "save", {"ide_type": ide_type})
            conn.commit()

            # FAZ 7: AI seans özeti (ANTHROPIC_API_KEY varsa)
            working_dir = Path(record["working_dir"])
            summary = save_session_summary(conn, ctx_id, working_dir)
        except Exception as e:
            return _err(f"DB yazma hatası: {e}")
        finally:
            conn.close()

        result = {
            "status": "saved",
            "name": ctx_name,
            "git_branch": record["git_branch"],
            "active_files_count": len(json.loads(record["active_files"])),
            "warnings": warnings,
        }
        if summary:
            result["session_summary"] = summary
            result["ai_note"] = "Bu seans AI tarafından özetlendi ve kaydedildi."
        else:
            result["ai_note"] = (
                "AI özeti üretilmedi. ANTHROPIC_API_KEY env var'ını ayarlarsan "
                "bir sonraki save'de otomatik özet üretilir."
            )

        return _ok(result)

    # ── switch_context ────────────────────────────────────────────────────────
    elif name == "switch_context":
        ctx_name     = arguments.get("name", "").strip()
        dry_run      = arguments.get("dry_run", False)
        wait_seconds = float(arguments.get("wait_seconds", 2.0))

        conn = get_db()
        try:
            row = conn.execute(
                "SELECT * FROM contexts WHERE name = ?", (ctx_name,)
            ).fetchone()
            if row is None:
                return _err(f"'{ctx_name}' bulunamadı.", "not_found")

            row = dict(row)
            working_dir = Path(row["working_dir"])
            live_git    = capture_git_state(working_dir)
            positions   = json.loads(row["cursor_positions"] or "[]")
            warnings: list[str] = []

            if live_git.available and live_git.dirty:
                warnings.append(
                    "Kaydedilmemiş değişiklikler var. "
                    "resolve_git_state ile stash/commit/discard yapabilirsin."
                )

            # FAZ 7: hoş geldin mesajı
            welcome = build_welcome_message(row, live_git.branch, live_git.dirty)

            if dry_run:
                return _ok({
                    "status": "dry_run",
                    "welcome_brief": welcome,
                    "target": row["working_dir"],
                    "ide_type": row["ide_type"],
                    "branch_saved": row["git_branch"],
                    "branch_now": live_git.branch,
                    "dirty": live_git.dirty,
                    "files_to_reopen": len(positions),
                    "warnings": warnings,
                })

            launch = launch_ide_soft(row["ide_type"], working_dir)
            if not launch.launched:
                log_event(conn, row["id"], "switch_error", {"error": launch.error})
                conn.commit()
                return _err(f"IDE başlatılamadı: {launch.error}")

            reopen_results: list[dict] = []
            if positions:
                time.sleep(wait_seconds)
                results = reopen_files(row["ide_type"], positions)
                reopen_results = [{"file": r.file, "ok": r.ok,
                                    "error": r.error} for r in results]

            conn.execute(
                "UPDATE contexts SET last_opened_at=? WHERE id=?",
                (now_iso(), row["id"]),
            )
            log_event(conn, row["id"], "switch", {"ide_type": row["ide_type"]})
            conn.commit()

            # Aktif projeyi güncelle (Resources için)
            _current_project_dir = working_dir

        except Exception as e:
            return _err(f"switch hatası: {e}")
        finally:
            conn.close()

        return _ok({
            "status": "switched",
            "name": ctx_name,
            "cli_used": launch.cli_used,
            "files_reopened": reopen_results,
            "warnings": warnings,
            "welcome_brief": welcome,
        })

    # ── list_contexts ─────────────────────────────────────────────────────────
    elif name == "list_contexts":
        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT name, working_dir, ide_type, git_branch, "
                "updated_at, session_summary FROM contexts ORDER BY updated_at DESC"
            ).fetchall()
        finally:
            conn.close()

        contexts = []
        for r in rows:
            d = dict(r)
            # Özet varsa ilk 100 karakteri göster
            if d.get("session_summary"):
                d["session_summary_preview"] = d["session_summary"][:100] + "..."
            del d["session_summary"]
            contexts.append(d)

        return _ok({"status": "ok", "count": len(contexts), "contexts": contexts})

    # ── preview_context ───────────────────────────────────────────────────────
    elif name == "preview_context":
        ctx_name = arguments.get("name", "").strip()
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT * FROM contexts WHERE name = ?", (ctx_name,)
            ).fetchone()
        finally:
            conn.close()

        if row is None:
            return _err(f"'{ctx_name}' bulunamadı.", "not_found")

        row = dict(row)
        live = capture_git_state(Path(row["working_dir"]))
        warnings: list[str] = []
        if not live.available:
            warnings.append(f"git okunamadı: {live.error}")
        else:
            if live.branch != row["git_branch"]:
                warnings.append(
                    f"Branch değişmiş: {row['git_branch']!r} → {live.branch!r}"
                )
            if live.dirty:
                warnings.append("Kaydedilmemiş değişiklikler var.")

        welcome = build_welcome_message(row, live.branch, live.dirty)

        return _ok({
            "status": "ok",
            "snapshot": row,
            "live_git": {"branch": live.branch, "dirty": live.dirty,
                          "stash_count": live.stash_count},
            "session_brief": welcome,
            "warnings": warnings,
        })

    # ── delete_context ────────────────────────────────────────────────────────
    elif name == "delete_context":
        ctx_name = arguments.get("name", "").strip()
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT id FROM contexts WHERE name=?", (ctx_name,)
            ).fetchone()
            if row is None:
                return _err(f"'{ctx_name}' bulunamadı.", "not_found")
            conn.execute("DELETE FROM context_events WHERE context_id=?", (row["id"],))
            conn.execute("DELETE FROM contexts WHERE id=?", (row["id"],))
            conn.commit()
        finally:
            conn.close()
        return _ok({"status": "deleted", "name": ctx_name})

    # ── resolve_git_state — FAZ 6 ─────────────────────────────────────────────
    elif name == "resolve_git_state":
        action   = arguments.get("action", "status")
        ctx_name = arguments.get("context_name", "").strip()

        # Çalışma dizini: context'ten al ya da cwd kullan
        cwd = Path.cwd()
        if ctx_name:
            conn = get_db()
            try:
                row = conn.execute(
                    "SELECT working_dir FROM contexts WHERE name=?", (ctx_name,)
                ).fetchone()
                if row:
                    cwd = Path(row["working_dir"])
            finally:
                conn.close()

        if action == "status":
            branch  = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd)
            status  = _run(["git", "status", "--short"], cwd)
            dirty   = bool(status.strip())
            return _ok({
                "status": "ok",
                "working_dir": str(cwd),
                "branch": branch,
                "dirty": dirty,
                "changed_files": status,
                "suggestion": (
                    "Kaydedilmemiş değişiklikler var. "
                    "Ne yapmak istiyorsun? "
                    "→ stash (güvenli), commit_wip (hızlı), discard (geri alınamaz)"
                ) if dirty else "Working tree temiz, geçiş yapılabilir.",
            })

        elif action == "stash":
            out = _run(["git", "stash", "push", "-m",
                        f"context-automator auto-stash {now_iso()}"], cwd)
            return _ok({
                "status": "ok",
                "action": "stash",
                "output": out,
                "message": "Değişiklikler stash'e alındı. İstediğinde git stash pop ile geri alınır.",
            })

        elif action == "commit_wip":
            _run(["git", "add", "-A"], cwd)
            ts = now_iso()[:16].replace("T", " ")
            out = _run(["git", "commit", "-m", f"WIP: auto-save {ts}"], cwd)
            return _ok({
                "status": "ok",
                "action": "commit_wip",
                "output": out,
                "message": "WIP commit oluşturuldu.",
            })

        elif action == "discard":
            out1 = _run(["git", "checkout", "--", "."], cwd)
            out2 = _run(["git", "clean", "-fd"], cwd)
            return _ok({
                "status": "ok",
                "action": "discard",
                "output": f"{out1}\n{out2}".strip(),
                "warning": "Tüm kaydedilmemiş değişiklikler silindi. Bu işlem geri alınamaz.",
            })

        return _err(f"Geçersiz action: {action}")

    return _err(f"Bilinmeyen tool: {name}", "unknown_tool")


# ---------------------------------------------------------------------------
# Giriş noktası
# ---------------------------------------------------------------------------

async def _serve() -> None:
    async with stdio_server() as (r, w):
        await app.run(r, w, app.create_initialization_options())


def main() -> None:
    import asyncio
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
