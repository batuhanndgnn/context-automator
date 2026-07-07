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
import time
from pathlib import Path
# NOT: `vision_processor` importu buradan kaldırıldı. Bu paketin bağımlılıkları
# (opencv-python, mss, numpy) pyproject.toml'da deklare edilmemiş ve .venv'de
# kurulu değildi -- modül seviyesinde (fonksiyon içinde değil, dosyanın en
# üstünde) yapılan bu import, MCP sunucusu her başlatıldığında
# ModuleNotFoundError ile SUNUCUNUN TAMAMEN ÇÖKMESİNE yol açıyordu, hatta
# vision özelliği hiç kullanılmasa bile. Vision entegrasyonu ayrı bir fazda,
# opsiyonel/lazy bir import olarak (yalnızca gerçekten kullanılacağı yerde,
# try/except ile) geri eklenmeli.
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

from context_automator.util import (
    build_snapshot, upsert_context, get_db, log_event, now_iso, logger
)
from context_automator.gitutil import run_git
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
    logger.error(f"Sistem Hatası [{code}]: {msg}")
    return [types.TextContent(type="text",
                               text=json.dumps({"status": code, "error": msg},
                                               ensure_ascii=False))]


# NOT: Önceki `_run()` + `_RUN_ERROR_SENTINEL` deseni gitutil.run_git() ile
# değiştirildi (bkz. gitutil.py docstring'i). Tüm başarı/başarısızlık kararı
# artık returncode'a dayanıyor, İngilizce çıktı metnine değil -- bu locale
# bağımsızlığı sağlıyor ve mcp_server/git_state/session_logger arasındaki
# 3 kopya git-çalıştırma mantığını tek yere indiriyor.


# ---------------------------------------------------------------------------
# FAZ 5 — MCP Resources
# ---------------------------------------------------------------------------

@app.list_resources()
async def list_resources() -> list[types.Resource]:
    logger.info("list_resources tetiklendi.")
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
    except Exception as e:
        logger.error(f"Resource listeleme veritabanı hatası: {str(e)}", exc_info=True)
    finally:
        conn.close()

    return resources


@app.read_resource()
async def read_resource(uri: str) -> str:
    global _current_project_dir
    cwd = _current_project_dir or Path.cwd()
    logger.info(f"read_resource tetiklendi: {uri}")

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
        except Exception as e:
            logger.error(f"Dizin yapısı okunurken hata: {str(e)}", exc_info=True)

        return "\n".join(lines)

    # context://current-git-status
    if uri == "context://current-git-status":
        branch = run_git(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd).output
        status = run_git(["git", "status", "--short"], cwd).output
        log    = run_git(["git", "log", "--oneline", "-10",
                          "--pretty=format:%h %s (%ar)"], cwd).output
        diff   = run_git(["git", "diff", "HEAD"], cwd).output

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
        except Exception as e:
            logger.error(f"Seans geçmişi okunurken DB hatası: {str(e)}", exc_info=True)
            row = None
        finally:
            conn.close()

        if not row:
            logger.warning(f"Seans geçmişi okunamadı: '{ctx_name}' bulunamadı.")
            return f"'{ctx_name}' adında kayıtlı context bulunamadı."

        row = dict(row)
        live = capture_git_state(Path(row["working_dir"]))
        return build_welcome_message(row, live.branch, live.dirty)

    logger.warning(f"Bilinmeyen resource URI istendi: {uri}")
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
        logger.info(f"save_context tetiklendi: Hedef -> {ctx_name}")
        
        if not ctx_name:
            return _err("'name' boş olamaz.", "validation_error")

        ide_type = arguments.get("ide")
        dry_run  = arguments.get("dry_run", False)

        record, warnings = build_snapshot(ctx_name, ide_type)

        if dry_run:
            logger.info(f"save_context dry_run tamamlandı: {ctx_name}")
            return _ok({"status": "dry_run", "would_save": record,
                         "warnings": warnings})

        conn = get_db()
        try:
            ctx_id = upsert_context(conn, record)
            log_event(conn, ctx_id, "save", {"ide_type": ide_type})
            conn.commit()

            # FAZ 7/8: AI seans özeti. Önce MCP Sampling denenir (client
            # destekliyorsa) — sunucu kendi API key'ini kullanmaz, maliyet ve
            # model seçimi Claude Desktop tarafında kalır. Sampling mevcut
            # değilse ANTHROPIC_API_KEY ile BYOK fallback'e düşülür.
            working_dir = Path(record["working_dir"])
            try:
                mcp_session = app.request_context.session
            except LookupError:
                mcp_session = None
            summary = await save_session_summary(conn, ctx_id, working_dir,
                                                  mcp_session=mcp_session)
            logger.info(f"Başarıyla kaydedildi: {ctx_name}")
        except Exception as e:
            logger.error(f"save_context DB yazma hatası: {str(e)}", exc_info=True)
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
        logger.info(f"switch_context tetiklendi: Hedef proje -> {ctx_name}")

        conn = get_db()
        try:
            row = conn.execute(
                "SELECT * FROM contexts WHERE name = ?", (ctx_name,)
            ).fetchone()
            if row is None:
                logger.warning(f"switch_context başarısız: '{ctx_name}' bulunamadı.")
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
                logger.info(f"switch_context dry_run tamamlandı: {ctx_name}")
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
                logger.error(f"IDE başlatılamadı ({row['ide_type']}): {launch.error}")
                return _err(f"IDE başlatılamadı: {launch.error}")

            reopen_results: list[dict] = []
            if positions:
                time.sleep(wait_seconds)
                results = reopen_files(row["ide_type"], positions)
                reopen_results = [{"file": r.file, "ok": r.ok,
                                    "error": r.error} for r in results]
                logger.info(f"{len(reopen_results)} dosya yeniden açıldı.")

            conn.execute(
                "UPDATE contexts SET last_opened_at=? WHERE id=?",
                (now_iso(), row["id"]),
            )
            log_event(conn, row["id"], "switch", {"ide_type": row["ide_type"]})
            conn.commit()

            # Aktif projeyi güncelle (Resources için)
            _current_project_dir = working_dir
            logger.info(f"switch_context başarıyla tamamlandı: {ctx_name}")

        except Exception as e:
            logger.error(f"switch_context sırasında beklenmeyen hata: {str(e)}", exc_info=True)
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
        logger.info("list_contexts tetiklendi.")
        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT name, working_dir, ide_type, git_branch, "
                "updated_at, session_summary FROM contexts ORDER BY updated_at DESC"
            ).fetchall()
        except Exception as e:
            logger.error(f"list_contexts DB okuma hatası: {str(e)}", exc_info=True)
            return _err(f"Listeleme hatası: {e}")
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
        logger.info(f"preview_context tetiklendi: {ctx_name}")
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT * FROM contexts WHERE name = ?", (ctx_name,)
            ).fetchone()
        except Exception as e:
            logger.error(f"preview_context DB okuma hatası: {str(e)}", exc_info=True)
            return _err(f"Okuma hatası: {e}")
        finally:
            conn.close()

        if row is None:
            logger.warning(f"preview_context başarısız: '{ctx_name}' bulunamadı.")
            return _err(f"'{ctx_name}' bulunamadı.", "not_found")

        row = dict(row)
        live = capture_git_state(Path(row["working_dir"]))
        warnings: list[str] = []
        if not live.available:
            warnings.append(f"git okunamadı: {live.error}")
            logger.warning(f"preview_context Git durumu okunamadı: {live.error}")
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
        logger.info(f"delete_context tetiklendi: {ctx_name}")
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT id FROM contexts WHERE name=?", (ctx_name,)
            ).fetchone()
            if row is None:
                logger.warning(f"delete_context başarısız: '{ctx_name}' bulunamadı.")
                return _err(f"'{ctx_name}' bulunamadı.", "not_found")
            conn.execute("DELETE FROM context_events WHERE context_id=?", (row["id"],))
            conn.execute("DELETE FROM contexts WHERE id=?", (row["id"],))
            conn.commit()
            logger.info(f"Başarıyla silindi: {ctx_name}")
        except Exception as e:
            logger.error(f"delete_context silme hatası: {str(e)}", exc_info=True)
            return _err(f"Silme hatası: {e}")
        finally:
            conn.close()
        return _ok({"status": "deleted", "name": ctx_name})

    # ── resolve_git_state — FAZ 6 ─────────────────────────────────────────────
    elif name == "resolve_git_state":
        action   = arguments.get("action", "status")
        ctx_name = arguments.get("context_name", "").strip()
        logger.info(f"resolve_git_state tetiklendi: Action -> {action}, Proje -> {ctx_name}")

        # Çalışma dizini: context_name verilmezse aktif projeye (switch_context'in
        # ayarladığı _current_project_dir) düş, o da yoksa MCP sunucusunun cwd'sine.
        # ÖNEMLİ: Burada hardcoded bir yol OLMAMALI — 'discard' geri alınamaz bir
        # işlem, yanlış dizinde çalışırsa veri kaybına yol açar.
        cwd = _current_project_dir or Path.cwd()
        logger.info(f"Git işlemi için kök dizin: {cwd}")

        if ctx_name:
            conn = get_db()
            try:
                row = conn.execute(
                    "SELECT working_dir FROM contexts WHERE name=?", (ctx_name,)
                ).fetchone()
                if row:
                    cwd = Path(row["working_dir"])
            except Exception as e:
                logger.error(f"resolve_git_state çalışma dizini bulma hatası: {str(e)}", exc_info=True)
            finally:
                conn.close()

        if action == "status":
            branch_res = run_git(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd)
            status_res = run_git(["git", "status", "--short"], cwd)

            if not status_res.ok:
                return _err(
                    "Git status okunurken beklenmedik bir hata oluştu — "
                    "'temiz' olarak varsayılmadı, ayrıntı için app.log'a bak. "
                    f"({status_res.exc or status_res.stderr})",
                    "git_status_error",
                )

            status = status_res.stdout
            dirty = bool(status.strip())
            return _ok({
                "status": "ok",
                "working_dir": str(cwd),
                "branch": branch_res.stdout,
                "dirty": dirty,
                "changed_files": status,
                "suggestion": (
                    "Kaydedilmemiş değişiklikler var. "
                    "Ne yapmak istiyorsun? "
                    "→ stash (güvenli), commit_wip (hızlı), discard (geri alınamaz)"
                ) if dirty else "Working tree temiz, geçiş yapılabilir.",
            })

        elif action == "stash":
            res = run_git(["git", "stash", "push", "-m",
                           f"context-automator auto-stash {now_iso()}"], cwd)
            if not res.ok:
                return _err("Git stash sırasında bir hata oluştu: "
                            f"{res.exc or res.stderr}", "git_stash_error")
            logger.info(f"Git stash uygulandı: {cwd}")
            return _ok({
                "status": "ok",
                "action": "stash",
                "output": res.stdout,
                "message": "Değişiklikler stash'e alındı. İstediğinde git stash pop ile geri alınır.",
            })

        elif action == "commit_wip":
            # Önce ekleyebiliyor muyuz kontrol edelim
            add_res = run_git(["git", "add", "-u"], cwd)
            logger.info(f"Git add sonucu: {add_res.stdout or add_res.stderr}")
            if not add_res.ok:
                return _err("Git add sırasında bir hata oluştu: "
                            f"{add_res.exc or add_res.stderr}", "git_add_error")

            ts = now_iso()[:16].replace("T", " ")
            commit_msg = f"WIP: auto-save {ts}"
            commit_res = run_git(["git", "commit", "-m", commit_msg], cwd)

            logger.info(f"Git commit sonucu (rc={commit_res.returncode}): "
                        f"{commit_res.stdout or commit_res.stderr}")

            # NOT: Önceden başarı/başarısızlık İngilizce çıktı metni
            # üzerinden ("nothing to commit", "fatal:" gibi sabit string'ler)
            # tespit ediliyordu -- kullanıcının git'i başka bir dilde
            # kuruluysa (ör. Türkçe git.exe) bu kırılırdı. Artık SADECE
            # returncode'a bakıyoruz (0 = başarılı), dil/locale'den tamamen
            # bağımsız. "commit edilecek bir şey yok" durumunda da git zaten
            # non-zero exit code döner, bu yüzden ek string kontrolüne gerek
            # kalmadı.
            if commit_res.exc or commit_res.timed_out:
                return _err("Git commit sırasında beklenmedik bir hata oluştu, "
                            "ayrıntı için app.log'a bak.", "git_commit_error")

            committed = commit_res.ok
            out = commit_res.stdout if committed else commit_res.stderr

            return _ok({
                "status": "ok" if committed else "not_committed",
                "output": out,
                "message": (f"Commit oluşturuldu: {commit_msg}" if committed
                           else "Commit oluşturulamadı — çıktıyı kontrol et."),
            })

        elif action == "discard":
            res1 = run_git(["git", "checkout", "--", "."], cwd)
            if not res1.ok:
                return _err("Git checkout sırasında bir hata oluştu "
                            "— GERİ ALINAMAZ işlem güvenlik amacıyla durduruldu: "
                            f"{res1.exc or res1.stderr}", "git_discard_error")
            res2 = run_git(["git", "clean", "-fd"], cwd)
            if not res2.ok:
                return _err("Git clean sırasında bir hata oluştu "
                            f"(checkout kısmı zaten uygulanmış olabilir!): "
                            f"{res2.exc or res2.stderr}", "git_discard_error")
            logger.warning(f"Git discard uygulandı (GERİ ALINAMAZ): {cwd}")
            return _ok({
                "status": "ok",
                "action": "discard",
                "output": f"{res1.stdout}\n{res2.stdout}".strip(),
                "warning": "Tüm kaydedilmemiş değişiklikler silindi. Bu işlem geri alınamaz.",
            })

        logger.warning(f"Geçersiz git action: {action}")
        return _err(f"Geçersiz action: {action}")

    logger.warning(f"Bilinmeyen tool çağrıldı: {name}")
    return _err(f"Bilinmeyen tool: {name}", "unknown_tool")


# ---------------------------------------------------------------------------
# Giriş noktası
# ---------------------------------------------------------------------------

async def _serve() -> None:
    async with stdio_server() as (r, w):
        await app.run(r, w, app.create_initialization_options())


def main() -> None:
    # Sunucu daha başlamadan loga yazıyoruz
    logger.info("--- MCP SUNUCUSU BAŞLATILIYOR ---")
    import asyncio
    asyncio.run(_serve())


if __name__ == "__main__":
    main()