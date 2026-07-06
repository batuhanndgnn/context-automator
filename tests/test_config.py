"""config.py icin testler -- pydantic-settings ile ortam degiskeni okuma
davranisini dogrular."""
import pytest

from context_automator.config import Settings


class TestSettings:
    def test_defaults_when_no_env_vars_set(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("CONTEXT_AUTOMATOR_CURSOR_CLI", raising=False)
        monkeypatch.delenv("CONTEXT_AUTOMATOR_VSCODE_CLI", raising=False)
        monkeypatch.delenv("CONTEXT_AUTOMATOR_DB_PATH", raising=False)
        s = Settings(_env_file=None)  # .env dosyasini da devre disi birak
        assert s.anthropic_api_key is None
        assert s.cursor_cli_override is None
        assert s.db_path_override is None
        assert s.log_level == "DEBUG"

    def test_reads_anthropic_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-123")
        s = Settings(_env_file=None)
        assert s.anthropic_api_key == "sk-ant-test-123"

    def test_reads_ide_cli_overrides(self, monkeypatch):
        monkeypatch.setenv("CONTEXT_AUTOMATOR_CURSOR_CLI", r"C:\custom\cursor.cmd")
        s = Settings(_env_file=None)
        assert s.cursor_cli_override == r"C:\custom\cursor.cmd"
        assert s.cli_override_for("cursor") == r"C:\custom\cursor.cmd"
        assert s.cli_override_for("vscode") is None

    def test_db_path_override_is_coerced_to_path(self, monkeypatch, tmp_path):
        custom_path = tmp_path / "custom" / "contexts.db"
        monkeypatch.setenv("CONTEXT_AUTOMATOR_DB_PATH", str(custom_path))
        s = Settings(_env_file=None)
        assert s.db_path_override == custom_path

    def test_unknown_env_vars_do_not_raise(self, monkeypatch):
        # extra="ignore" -- .env'de veya ortamda bilinmeyen key'ler varsa
        # (ör. bu makinede ayarlanmis alakasiz bir env var) patlamamali.
        monkeypatch.setenv("SOME_UNRELATED_VAR", "whatever")
        Settings(_env_file=None)  # exception firlatmamali
