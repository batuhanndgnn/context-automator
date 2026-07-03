"""Ortak yardımcı fonksiyonlar — cli.py ve mcp_server.py paylaşır.

Faz F: CLI ve MCP'de aynı mantık iki yerde duruyordu. Buraya taşındı.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
import os
import logging
from logging.handlers import RotatingFileHandler

from context_automator.capture.git_state import capture_git_state
from context_automator.adapters.vscode_family import get_ide_configs, read_editor_state
from context_automator.db.schema import ensure_schema, get_connection, default_db_path

# Proje kök dizininde 'logs' klasörü oluştur
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
# src/context_automator/util.py içindeki ilgili kısmı şu şekilde değiştir:
LOG_DIR = r"C:\Users\bdogan\Desktop\context-automator-clean\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, 'app.log')

def setup_logger():
    log = logging.getLogger("ContextAutomator")
    log.setLevel(logging.DEBUG)

    if not log.handlers:
        file_handler = RotatingFileHandler(LOG_FILE, maxBytes=5*1024*1024, backupCount=3, encoding='utf-8')
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s')
        file_handler.setFormatter(formatter)
        log.addHandler(file_handler)
        
        # PRO ADIM: Logları anında diske yazmaya zorla (flush)
        file_handler.doRollover = lambda: None 
        
    return log

# Tüm projede kullanılacak global logger objesi
logger = setup_logger() 

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_db():
    conn = get_connection(default_db_path())
    ensure_schema(conn)
    return conn


def log_event(conn, context_id: int, event_type: str, payload: dict) -> None:
    conn.execute(
        "INSERT INTO context_events (context_id, event_type, payload, created_at) "
        "VALUES (?, ?, ?, ?)",
        (context_id, event_type, json.dumps(payload, ensure_ascii=False), now_iso()),
    )


def build_snapshot(name: str, ide_type: str | None,
                   working_dir: Path | None = None) -> tuple[dict, list[str]]:
    """Capture katmanını çalıştırır.
    Döner: (kayıt dict'i, uyarı listesi)
    """
    if working_dir is None:
        working_dir = Path.cwd()

    git = capture_git_state(working_dir)
    warnings: list[str] = []

    if not git.available:
        warnings.append(f"git okunamadı: {git.error}")

    editor_state = None
    if ide_type and ide_type in get_ide_configs():
        editor_state = read_editor_state(get_ide_configs()[ide_type], working_dir)
        if editor_state.error:
            warnings.append(f"editor state hatası: {editor_state.error}")
        elif editor_state.source == "history-fallback":
            warnings.append(
                "Dosya listesi history.entries fallback'inden alındı (yaklaşık). "
                "Kesin veri için IDE'yi normal kapat/aç."
            )

    record = {
        "name": name,
        "working_dir": str(working_dir),
        "ide_type": ide_type or "unknown",
        "git_branch": git.branch,
        "git_dirty": int(git.dirty),
        "git_stash_count": git.stash_count,
        "active_files": json.dumps(
            editor_state.active_files if editor_state else []
        ),
        "cursor_positions": json.dumps(
            editor_state.cursor_positions if editor_state else []
        ),
        "terminal_commands": json.dumps([]),
        "window_layout": (
            editor_state.layout_raw
            if (editor_state and editor_state.layout_raw)
            else json.dumps({})
        ),
    }
    return record, warnings


def upsert_context(conn, record: dict) -> int:
    """INSERT OR UPDATE, context id'sini döner."""
    ts = now_iso()
    conn.execute(
        """
        INSERT INTO contexts
            (name, working_dir, ide_type, git_branch, git_dirty,
             git_stash_count, active_files, cursor_positions,
             terminal_commands, window_layout, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            working_dir      = excluded.working_dir,
            ide_type         = excluded.ide_type,
            git_branch       = excluded.git_branch,
            git_dirty        = excluded.git_dirty,
            git_stash_count  = excluded.git_stash_count,
            active_files     = excluded.active_files,
            cursor_positions = excluded.cursor_positions,
            terminal_commands= excluded.terminal_commands,
            window_layout    = excluded.window_layout,
            updated_at       = excluded.updated_at
        """,
        (
            record["name"], record["working_dir"], record["ide_type"],
            record["git_branch"], record["git_dirty"], record["git_stash_count"],
            record["active_files"], record["cursor_positions"],
            record["terminal_commands"], record["window_layout"], ts, ts,
        ),
    )
    row = conn.execute(
        "SELECT id FROM contexts WHERE name = ?", (record["name"],)
    ).fetchone()
    conn.commit()
    return row["id"]
