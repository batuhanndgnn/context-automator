"""adapters/vscode_family.py için birim testler.

Bu dosya özellikle to_vscode_uri / vscode_uri_to_path round-trip'ini
test eder çünkü bu, projenin en kritik ve en kırılgan mantığıydı (Faz 0
spike'ında bulunan URI format uyuşmazlığı bug'ı buradaydı). Bir regresyon
burada sessizce "aktif dosyalar" listesinin boş dönmesine yol açar --
hatasız ama yanlış davranan bir bug, testsiz yakalanması zor.
"""
import json

import pytest

from context_automator.adapters.vscode_family import (
    to_vscode_uri,
    vscode_uri_to_path,
    _extract_line_col,
    _walk,
    find_workspace_storage_dir,
    IDEConfig,
)


class TestUriRoundTrip:
    def test_to_vscode_uri_basic(self, tmp_path):
        # Path.resolve() gerçek bir dizin gerektirmiyor ama var olan bir
        # yolu vermek testin platform-bağımsız çalışmasını garanti eder.
        p = tmp_path / "Projects" / "context-automator"
        uri = to_vscode_uri(p)
        assert uri.startswith("file:///")
        # Sürücü harfi küçük ve %3A ile encode edilmiş olmalı (bkz. docstring
        # spike bulgusu: VS Code file:///c%3A/... formatını kullanıyor)
        assert "%3A" in uri
        assert ":" not in uri.split("%3A")[0][-1:]  # ':' çıplak değil

    def test_round_trip_preserves_path(self, tmp_path):
        p = tmp_path / "Users" / "bdogan" / "Projects" / "demo"
        uri = to_vscode_uri(p)
        back = vscode_uri_to_path(uri)
        assert back is not None
        assert back.lower() == str(p).lower()

    def test_vscode_uri_to_path_rejects_non_file_uri(self):
        assert vscode_uri_to_path("https://example.com") is None

    def test_vscode_uri_to_path_handles_encoded_drive(self):
        # Gerçek VS Code çıktısına birebir örnek (docstring'teki spike verisi)
        uri = "file:///c%3A/Users/bdogan/Projects/context-automator"
        path = vscode_uri_to_path(uri)
        assert path == "C:\\Users\\bdogan\\Projects\\context-automator"


class TestExtractLineCol:
    def test_direct_line_number(self):
        sel = {"startLineNumber": 42, "startColumn": 7}
        line, col = _extract_line_col(sel)
        assert (line, col) == (42, 7)

    def test_nested_selection(self):
        sel = {"viewState": {"startLineNumber": 3, "startColumn": 1}}
        line, col = _extract_line_col(sel)
        assert (line, col) == (3, 1)

    def test_list_takes_first_element(self):
        sel = [{"startLineNumber": 10, "startColumn": 2}, {"startLineNumber": 99}]
        line, col = _extract_line_col(sel)
        assert (line, col) == (10, 2)

    def test_unrecognized_shape_returns_none(self):
        assert _extract_line_col({"unrelated": True}) == (None, None)
        assert _extract_line_col(None) == (None, None)


class TestWalkExtraction:
    def test_finds_file_uri_in_nested_structure(self):
        data = {
            "editors": [
                {
                    "resource": "file:///c%3A/proj/main.py",
                    "selection": {"startLineNumber": 5, "startColumn": 1},
                }
            ]
        }
        found = []
        _walk(data, found)
        assert len(found) == 1
        assert found[0]["uri"] == "file:///c%3A/proj/main.py"
        assert found[0]["line"] == 5

    def test_walks_through_embedded_json_string(self):
        # memento şeması bazen dict yerine JSON-string olarak geliyor;
        # _walk bunu recursive olarak parse edip açabilmeli.
        inner = {"resource": "file:///c%3A/proj/util.py", "selection": None}
        data = {"editors": json.dumps([inner])}
        found = []
        _walk(data, found)
        assert len(found) == 1
        assert found[0]["uri"] == "file:///c%3A/proj/util.py"

    def test_ignores_non_file_resources(self):
        data = {"resource": "untitled:Untitled-1"}
        found = []
        _walk(data, found)
        assert found == []


class TestFindWorkspaceStorageDir:
    def test_returns_none_when_storage_dir_missing(self, tmp_path):
        ide = IDEConfig("vscode", tmp_path / "does-not-exist")
        result = find_workspace_storage_dir(ide, tmp_path)
        assert result is None

    def test_matches_workspace_by_folder_uri(self, tmp_path):
        storage = tmp_path / "workspaceStorage"
        ws_dir = storage / "abc123"
        ws_dir.mkdir(parents=True)
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()

        (ws_dir / "workspace.json").write_text(
            json.dumps({"folder": to_vscode_uri(project_dir)}),
            encoding="utf-8",
        )

        ide = IDEConfig("vscode", storage)
        result = find_workspace_storage_dir(ide, project_dir)
        assert result == ws_dir

    def test_no_match_for_different_project(self, tmp_path):
        storage = tmp_path / "workspaceStorage"
        ws_dir = storage / "abc123"
        ws_dir.mkdir(parents=True)
        other_dir = tmp_path / "other"
        other_dir.mkdir()
        (ws_dir / "workspace.json").write_text(
            json.dumps({"folder": to_vscode_uri(other_dir)}), encoding="utf-8",
        )

        ide = IDEConfig("vscode", storage)
        target_dir = tmp_path / "myproject"
        target_dir.mkdir()
        assert find_workspace_storage_dir(ide, target_dir) is None
