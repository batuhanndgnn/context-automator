"""SQLite şema tanımı ve migration.

v1 kapsamı: terminal_commands sütunu şemada duruyor (gelecekte kullanılacak)
ama capture katmanı v1'de bunu doldurmuyor - bilinçli karar, bkz. V2_BACKLOG.md.
"""

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

DDL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS contexts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    working_dir TEXT NOT NULL,
    ide_type TEXT NOT NULL DEFAULT 'cursor',
    git_branch TEXT,
    git_dirty INTEGER DEFAULT 0,
    git_stash_count INTEGER DEFAULT 0,
    active_files TEXT,
    cursor_positions TEXT,
    terminal_commands TEXT,
    session_summary TEXT,
    window_layout TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_opened_at TEXT
);

CREATE TABLE IF NOT EXISTS context_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    context_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    payload TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (context_id) REFERENCES contexts(id)
);
"""


def get_connection(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(DDL)
    cur = conn.execute("SELECT version FROM schema_version")
    row = cur.fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,)
        )
    conn.commit()


def default_db_path() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "contexts.db"
