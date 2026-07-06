"""context-automator CLI — v1 komutları: save list preview delete switch debug-state."""

import argparse
import json
import sys
import time
from pathlib import Path

from context_automator.util import (
    build_snapshot, upsert_context, get_db, log_event, now_iso,
)
from context_automator.capture.git_state import capture_git_state
from context_automator.adapters.vscode_family import get_ide_configs, debug_dump_state
from context_automator.restore.ide_launcher import launch_ide_soft
from context_automator.restore.file_restorer import reopen_files
from context_automator.capture.session_logger import generate_session_summary_via_api, gather_session_data


# ---------------------------------------------------------------------------
# save
# ---------------------------------------------------------------------------
def cmd_save(args):
    record, warnings = build_snapshot(args.name, args.ide)

    print("--- snapshot (dry preview) ---")
    print(json.dumps(record, indent=2, ensure_ascii=False))
    for w in warnings:
        print(f"[uyarı] {w}")

    if args.dry_run:
        print("\n[dry-run] hiçbir şey kaydedilmedi.")
        return 0

    conn = get_db()
    try:
        ctx_id = upsert_context(conn, record)
        log_event(conn, ctx_id, "save", {"ide_type": args.ide})
        conn.commit()

        # Not: CLI'nin bir MCP session'ı yok, dolayısıyla Sampling kullanamaz —
        # sadece ANTHROPIC_API_KEY tanımlıysa (BYOK) özet üretir. MCP aracı
        # (save_context) önce Sampling'i dener, o başarısız olursa aynı BYOK
        # yoluna düşer.
        session_data = gather_session_data(Path(record["working_dir"]))
        summary = generate_session_summary_via_api(session_data)
        if summary:
            conn.execute(
                "UPDATE contexts SET session_summary = ? WHERE id = ?",
                (summary, ctx_id),
            )
            conn.commit()
            print(f"\n[AI özet] {summary}")
    finally:
        conn.close()

    print(f"\nKaydedildi: '{args.name}'")
    if not record["git_branch"]:
        print("[bilgi] git branch okunamadı — git repo'su olan bir dizinde mi çalıştırıyorsun?")
    return 0


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------
def cmd_list(args):
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT name, ide_type, git_branch, working_dir, updated_at "
            "FROM contexts ORDER BY updated_at DESC"
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        print("Henüz kayıtlı context yok. `context-automator save <isim>` ile başla.")
        return 0

    for r in rows:
        print(f"  {r['name']:<22} {r['ide_type']:<8} "
              f"branch={str(r['git_branch']):<15} {r['working_dir']}")
    return 0


# ---------------------------------------------------------------------------
# preview
# ---------------------------------------------------------------------------
def cmd_preview(args):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM contexts WHERE name = ?", (args.name,)
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        print(f"'{args.name}' bulunamadı.")
        return 1

    print(json.dumps(dict(row), indent=2, ensure_ascii=False))

    live = capture_git_state(Path(row["working_dir"]))
    print("\n--- canlı git durumu ---")
    if not live.available:
        print(f"[uyarı] git okunamadı: {live.error}")
    else:
        if live.branch != row["git_branch"]:
            print(f"[bilgi] branch değişmiş: kayıtlı={row['git_branch']!r} → şimdi={live.branch!r}")
        if live.dirty:
            print("[uyarı] kaydedilmemiş değişiklikler var — geçiş öncesi commit/stash öner.")
        else:
            print("[bilgi] working tree temiz.")
    return 0


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------
def cmd_delete(args):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id FROM contexts WHERE name = ?", (args.name,)
        ).fetchone()
        if row is None:
            print(f"'{args.name}' bulunamadı.")
            return 1
        conn.execute("DELETE FROM context_events WHERE context_id = ?", (row["id"],))
        conn.execute("DELETE FROM contexts WHERE id = ?", (row["id"],))
        conn.commit()
    finally:
        conn.close()
    print(f"Silindi: '{args.name}'")
    return 0


# ---------------------------------------------------------------------------
# switch
# ---------------------------------------------------------------------------
def cmd_switch(args):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM contexts WHERE name = ?", (args.name,)
        ).fetchone()
        if row is None:
            print(f"'{args.name}' bulunamadı.")
            return 1

        row = dict(row)
        working_dir = Path(row["working_dir"])
        live = capture_git_state(working_dir)
        positions = json.loads(row["cursor_positions"] or "[]")

        print(f"Hedef    : {working_dir}")
        print(f"IDE      : {row['ide_type']}")
        print(f"Branch   : kayıtlı={row['git_branch']}  canlı={live.branch}")
        print(f"Dosyalar : {len(positions)} adet yeniden açılacak")

        if live.available and live.dirty:
            print("[uyarı] kaydedilmemiş değişiklikler var (soft mode — mevcut pencere kapatılmaz).")

        if args.dry_run:
            print("[dry-run] IDE açılmadı.")
            return 0

        launch = launch_ide_soft(row["ide_type"], working_dir)
        if not launch.launched:
            print(f"[hata] IDE başlatılamadı: {launch.error}")
            log_event(conn, row["id"], "switch_error", {"error": launch.error})
            conn.commit()
            return 1

        print(f"Açılıyor: {launch.cli_used}")
        if positions:
            time.sleep(args.wait_seconds)
            results = reopen_files(row["ide_type"], positions)
            ok = sum(1 for r in results if r.ok)
            print(f"{ok}/{len(results)} dosya yeniden açıldı.")

        conn.execute(
            "UPDATE contexts SET last_opened_at=? WHERE id=?", (now_iso(), row["id"])
        )
        log_event(conn, row["id"], "switch", {"ide_type": row["ide_type"]})
        conn.commit()
    finally:
        conn.close()
    return 0


# ---------------------------------------------------------------------------
# debug-state
# ---------------------------------------------------------------------------
def cmd_debug_state(args):
    ide_configs = get_ide_configs()
    if args.ide not in ide_configs:
        print(f"bilinmeyen ide: {args.ide}")
        return 1

    result = debug_dump_state(ide_configs[args.ide], Path.cwd())
    if "error" in result:
        print(f"[hata] {result['error']}")
        return 1

    print(f"workspace: {result['ws_dir']}")
    print(f"\n{len(result['all_keys'])} key:")
    for k in result["all_keys"]:
        flag = " ← file:// içeriyor" if k in result["keys_with_file_uri"] else ""
        print(f"  {k}{flag}")

    if result["keys_with_file_uri"]:
        print("\n--- file:// içeren değerler ---")
        for k, v in result["keys_with_file_uri"].items():
            print(f"\n## {k}\n{v}")
    return 0


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------
def build_parser():
    p = argparse.ArgumentParser(prog="context-automator")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("save")
    s.add_argument("name")
    s.add_argument("--ide", choices=["cursor", "vscode"])
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(func=cmd_save)

    sub.add_parser("list").set_defaults(func=cmd_list)

    pv = sub.add_parser("preview")
    pv.add_argument("name")
    pv.set_defaults(func=cmd_preview)

    d = sub.add_parser("delete")
    d.add_argument("name")
    d.set_defaults(func=cmd_delete)

    sw = sub.add_parser("switch")
    sw.add_argument("name")
    sw.add_argument("--dry-run", action="store_true")
    sw.add_argument("--wait-seconds", type=float, default=2.0)
    sw.set_defaults(func=cmd_switch)

    ds = sub.add_parser("debug-state")
    ds.add_argument("--ide", choices=["cursor", "vscode"], required=True)
    ds.set_defaults(func=cmd_debug_state)

    return p


def main():
    args = build_parser().parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
