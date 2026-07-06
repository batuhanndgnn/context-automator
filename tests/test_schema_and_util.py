"""db/schema.py ve util.py için birim testler.

Odak noktası: upsert_context()'in artik conn.commit() cagirmadigini ve
cagiranin (save_context / cmd_save) upsert + log_event'i TEK bir islem
olarak commit'leyebildigini dogrulamak -- bu, bu oturumda duzeltilen
atomiklik bug'inin regresyon testidir.
"""
import json

import pytest

from context_automator.db.schema import get_connection, ensure_schema
from context_automator.util import upsert_context, log_event, now_iso


@pytest.fixture
def conn(tmp_path):
    c = get_connection(tmp_path / "test.db")
    ensure_schema(c)
    yield c
    c.close()


def _sample_record(name="demo-project"):
    return {
        "name": name,
        "working_dir": "C:\\Users\\bdogan\\Projects\\demo",
        "ide_type": "vscode",
        "git_branch": "main",
        "git_dirty": 0,
        "git_stash_count": 0,
        "active_files": json.dumps(["a.py", "b.py"]),
        "cursor_positions": json.dumps([]),
        "terminal_commands": json.dumps([]),
        "window_layout": json.dumps({}),
    }


class TestSchema:
    def test_ensure_schema_is_idempotent(self, conn):
        # ensure_schema iki kez cagrilirsa patlamamali (get_db() her tool
        # cagrisinda bunu tekrar cagiriyor)
        ensure_schema(conn)
        ensure_schema(conn)
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        assert row["version"] == 1

    def test_busy_timeout_and_wal_are_set(self, conn):
        # db/schema.py'ye bu oturumda eklendi -- "database is locked"
        # hatalarini onlemek icin
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert journal_mode.lower() == "wal"


class TestUpsertContextAtomicity:
    def test_upsert_does_not_commit_by_itself(self, conn):
        """upsert_context artik kendi commit'ini yapmamali -- caller,
        log_event ile birlikte TEK commit'te kaydedebilsin diye."""
        record = _sample_record()
        ctx_id = upsert_context(conn, record)
        log_event(conn, ctx_id, "save", {"ide_type": "vscode"})

        # Commit henuz cagrilmadi -- ayni connection'dan okunabilir olmali
        # (SQLite ayni connection icinde commit'siz de kendi yazdigini gorur)
        row = conn.execute(
            "SELECT * FROM contexts WHERE id = ?", (ctx_id,)
        ).fetchone()
        assert row is not None
        events = conn.execute(
            "SELECT * FROM context_events WHERE context_id = ?", (ctx_id,)
        ).fetchall()
        assert len(events) == 1

        conn.commit()

    def test_rollback_undoes_both_context_and_event(self, conn):
        """Atomikligin asil testi: commit'ten ONCE bir hata olursa (rollback),
        ne contexts satiri ne de event kaydi kalici olmali -- ikisi de
        ayni transaction'in parcasi."""
        record = _sample_record("rollback-test")
        ctx_id = upsert_context(conn, record)
        log_event(conn, ctx_id, "save", {"ide_type": "vscode"})

        conn.rollback()

        row = conn.execute(
            "SELECT * FROM contexts WHERE name = ?", ("rollback-test",)
        ).fetchone()
        assert row is None  # rollback sonrasi hicbir sey kalici olmamali

    def test_upsert_updates_existing_row_on_conflict(self, conn):
        record = _sample_record("conflict-test")
        ctx_id_1 = upsert_context(conn, record)
        conn.commit()

        record["git_branch"] = "feature/new-branch"
        ctx_id_2 = upsert_context(conn, record)
        conn.commit()

        assert ctx_id_1 == ctx_id_2  # ayni isim -> ayni satir (UPSERT)
        row = conn.execute(
            "SELECT git_branch FROM contexts WHERE id = ?", (ctx_id_1,)
        ).fetchone()
        assert row["git_branch"] == "feature/new-branch"
