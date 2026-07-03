"""Cursor ve VS Code aynı motoru (Electron + workspaceStorage şeması)
paylaştığı için tek adapter, IDE tipine göre sadece path config değişiyor.

Faz 0 spike bulgusu (bdogan'ın makinesinden):
  - workspace.json içindeki 'folder' alanı şu formatta saklanıyor:
        file:///c%3A/Users/bdogan/Projects/context-automator
    yani: küçük harf sürücü harfi + ':' karakteri %3A olarak encode edilmiş.
    `Path.as_uri()` ise file:///C:/... üretir (büyük harf, çıplak ':') -
    bu yüzden eşleşme hiç tutmuyordu. to_vscode_uri() bunu düzeltir.

  - Açık dosyalar + imleç konumu şu key altında JSON olarak duruyor:
        memento/workbench.editors.files.textFileEditor
  - Editör panel/layout bilgisi:
        memento/workbench.parts.editor

NOT: VS Code'un memento JSON şeması iç yapıda değişebiliyor (sürüme göre
nested string-JSON olabiliyor). Bu yüzden _walk() sabit bir path'e
("data['editors'][0]['resource']" gibi) güvenmiyor, recursive olarak
'resource'/'uri' ve 'selection'/'viewState' anahtarlarını arıyor. Daha kırılgan
olmayan ama %100 garanti de vermeyen bir yaklaşım - gerçek veriyle çalıştıkça
gerekirse sıkılaştırılır.
"""

import json
import os
import re
import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote


@dataclass
class IDEConfig:
    name: str
    storage_dir: Path


def get_ide_configs() -> dict[str, IDEConfig]:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return {}
    base = Path(appdata)
    return {
        "cursor": IDEConfig("cursor", base / "Cursor" / "User" / "workspaceStorage"),
        "vscode": IDEConfig("vscode", base / "Code" / "User" / "workspaceStorage"),
    }


@dataclass
class EditorState:
    active_files: list[str] = field(default_factory=list)
    cursor_positions: list[dict] = field(default_factory=list)
    raw_keys_found: list[str] = field(default_factory=list)
    layout_raw: str | None = None
    editors_raw: str | None = None  # debug-state komutu için - ham JSON
    source: str = "none"            # "memento" | "history-fallback" | "none"
    error: str | None = None


# ---------------------------------------------------------------------------
# URI <-> Windows path dönüşümü
# ---------------------------------------------------------------------------

def to_vscode_uri(path: Path) -> str:
    """Windows yolunu VS Code/Cursor'ın workspace.json'da kullandığı
    file:///c%3A/... formatına çevirir."""
    posix = path.resolve().as_posix()
    m = re.match(r"^([a-zA-Z]):/(.*)$", posix)
    if m:
        drive, rest = m.groups()
        return f"file:///{drive.lower()}%3A/{rest}"
    return f"file://{posix}"


def vscode_uri_to_path(uri: str) -> str | None:
    """file:///c%3A/Users/... -> C:\\Users\\..."""
    if not uri.startswith("file://"):
        return None
    rest = unquote(uri[len("file://"):])
    m = re.match(r"^/([a-zA-Z]):/(.*)$", rest)
    if m:
        drive, tail = m.groups()
        return f"{drive.upper()}:\\{tail.replace('/', chr(92))}"
    return rest.replace("/", "\\")


def find_workspace_storage_dir(ide: IDEConfig, working_dir: Path) -> Path | None:
    """working_dir'e karşılık gelen workspaceStorage alt klasörünü bulur.

    Karşılaştırma case-insensitive ve sondaki '/' farklarına toleranslı -
    spike'ta gördüğümüz gibi IDE'ler arasında küçük format farkları olabiliyor.
    """
    if not ide.storage_dir.exists():
        return None
    target = to_vscode_uri(working_dir).rstrip("/").lower()
    for ws_dir in ide.storage_dir.iterdir():
        wj = ws_dir / "workspace.json"
        if not wj.exists():
            continue
        try:
            data = json.loads(wj.read_text(encoding="utf-8", errors="replace"))
        except Exception:  # noqa: BLE001
            continue
        folder = data.get("folder", "")
        if folder.rstrip("/").lower() == target:
            return ws_dir
    return None


def _open_db_readonly(db_path: Path) -> sqlite3.Connection:
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2)
        conn.execute("SELECT 1")
        return conn
    except sqlite3.OperationalError:
        tmp_copy = db_path.parent / f"_ctxauto_copy_{db_path.name}"
        shutil.copy2(db_path, tmp_copy)
        return sqlite3.connect(str(tmp_copy))


# ---------------------------------------------------------------------------
# memento JSON içinden dosya/satır/sütun çıkarma
# ---------------------------------------------------------------------------

def _try_json_loads(value):
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value


def _extract_line_col(sel) -> tuple[int | None, int | None]:
    """'selection'/'viewState' alanlarından satır/sütun çıkarır.

    Şema sürüme göre değişebiliyor: bazen {startLineNumber, startColumn}
    direkt burada, bazen bir kademe daha içeride (viewState.selection) oluyor -
    bu yüzden tek seviyeyle yetinmiyoruz.
    """
    if isinstance(sel, dict):
        if "startLineNumber" in sel or "line" in sel:
            return sel.get("startLineNumber") or sel.get("line"), \
                   sel.get("startColumn") or sel.get("column")
        nested = sel.get("selection") or sel.get("cursorState") or sel.get("viewState")
        if nested is not None:
            return _extract_line_col(nested)
    elif isinstance(sel, list) and sel:
        return _extract_line_col(sel[0])
    return None, None


def _walk(node, found: list[dict]) -> None:
    """memento yapısı içinde gömülü JSON string'leri açarak
    'resource' (dosya URI'si) ve satır/sütun bilgisini toplar."""
    if isinstance(node, str):
        parsed = _try_json_loads(node)
        if parsed is not node:
            _walk(parsed, found)
        return

    if isinstance(node, dict):
        resource = node.get("resource") or node.get("resourceJSON") or node.get("uri")
        sel = node.get("selection") or node.get("viewState") or node.get("cursorState")
        line, col = _extract_line_col(sel)

        if isinstance(resource, str) and resource.startswith("file://"):
            found.append({"uri": resource, "line": line, "col": col})

        for v in node.values():
            _walk(v, found)
        return

    if isinstance(node, list):
        for item in node:
            _walk(item, found)


def debug_dump_state(ide: IDEConfig, working_dir: Path,
                      max_value_len: int = 2000) -> dict:
    """Tüm ItemTable key/value çiftlerini tarar, içinde 'file://' veya
    encode edilmiş 'file%3A' geçen TÜM key'leri döner.

    Amaç: varsayılan key isimlerimiz (memento/workbench.editors.files...)
    yanlış/eski/farklı sürüm-spesifik olabilir - bu, gerçek key'i bulmak
    için kör tahmin yerine veriden yola çıkan bir keşif yöntemi.
    """
    ws_dir = find_workspace_storage_dir(ide, working_dir)
    if ws_dir is None:
        return {"error": f"workspace bulunamadı: {working_dir}"}
    db_path = ws_dir / "state.vscdb"
    if not db_path.exists():
        return {"error": "state.vscdb yok"}

    try:
        conn = _open_db_readonly(db_path)
        rows = conn.execute("SELECT key, value FROM ItemTable").fetchall()
        conn.close()
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}

    all_keys = []
    keys_with_file_uri = {}
    for key, raw in rows:
        all_keys.append(key)
        text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        if "file://" in text or "file%3A" in text:
            keys_with_file_uri[key] = text[:max_value_len]

    return {
        "ws_dir": str(ws_dir),
        "all_keys": sorted(all_keys),
        "keys_with_file_uri": keys_with_file_uri,
    }


def read_editor_state(ide: IDEConfig, working_dir: Path) -> EditorState:
    ws_dir = find_workspace_storage_dir(ide, working_dir)
    if ws_dir is None:
        return EditorState(error=f"{ide.name} için workspace bulunamadı: {working_dir}")

    db_path = ws_dir / "state.vscdb"
    if not db_path.exists():
        return EditorState(error="state.vscdb yok (workspace hiç state kaydetmemiş olabilir)")

    # Öncelikli hedef key'ler; olmayabilir (yeni/az kullanılmış workspace'lerde
    # IDE bu memento'ları henüz yazmamış olabiliyor - IDE normal kapanması
    # gerekiyor). history.entries her zaman vardır ve fallback olarak kullanılır.
    EDITOR_KEYS = [
        "memento/workbench.editors.files.textFileEditor",  # primer kaynak
        "workbench.parts.embeddedAuxBarEditor.state",       # Cursor-spesifik varyant
    ]
    HISTORY_KEY = "history.entries"   # fallback - son açılan dosyalar
    LAYOUT_KEY  = "memento/workbench.parts.editor"

    raw_values: dict[str, str] = {}
    keys: list[str] = []

    try:
        conn = _open_db_readonly(db_path)
        keys = sorted(r[0] for r in conn.execute("SELECT key FROM ItemTable"))

        def _get(key: str) -> str | None:
            row = conn.execute(
                "SELECT value FROM ItemTable WHERE key = ?", (key,)
            ).fetchone()
            if not row:
                return None
            raw = row[0]
            return raw.decode("utf-8") if isinstance(raw, bytes) else raw

        for k in EDITOR_KEYS:
            v = _get(k)
            if v:
                raw_values["editors"] = v
                break                   # ilk bulunan yeterli

        history_raw = _get(HISTORY_KEY)
        layout_raw  = _get(LAYOUT_KEY)
        conn.close()
    except Exception as e:  # noqa: BLE001
        return EditorState(error=str(e), raw_keys_found=keys)

    active_files: list[str] = []
    cursor_positions: list[dict] = []
    source_used = "none"

    # --- Yol 1: primer editor memento ---
    if "editors" in raw_values:
        parsed = _try_json_loads(raw_values["editors"])
        found: list[dict] = []
        _walk(parsed, found)
        seen: set[str] = set()
        for item in found:
            lp = vscode_uri_to_path(item["uri"])
            if not lp or lp in seen:
                continue
            seen.add(lp)
            active_files.append(lp)
            if item["line"] is not None:
                cursor_positions.append({"file": lp, "line": item["line"],
                                          "col": item.get("col")})
        if active_files:
            source_used = "memento"

    # --- Yol 2: history.entries fallback ---
    # Primer memento boş döndüyse (yeni workspace / IDE tam kapanmadıysa)
    # son açılan dosyaları history.entries'ten alıyoruz.
    # ÖNEMLİ: Bu liste kapanma sıralamasına göre, aktif sırasına göre değil —
    # "en son açılan" ile "save anında açık olan" aynı olmayabilir. Bu bir
    # yaklaşım, kesin değil; save çıktısında [history-fallback] olarak işaretleniyor.
    if not active_files and history_raw:
        hist = _try_json_loads(history_raw)
        found_h: list[dict] = []
        _walk(hist, found_h)
        seen_h: set[str] = set()
        for item in found_h:
            lp = vscode_uri_to_path(item["uri"])
            if not lp or lp in seen_h:
                continue
            seen_h.add(lp)
            active_files.append(lp)
            # history.entries satır/sütun bilgisi taşımıyor
        if active_files:
            source_used = "history-fallback"

    return EditorState(
        active_files=active_files,
        cursor_positions=cursor_positions,
        raw_keys_found=keys,
        layout_raw=layout_raw,
        editors_raw=raw_values.get("editors"),
        source=source_used,
    )
