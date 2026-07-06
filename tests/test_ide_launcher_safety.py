"""restore/ide_launcher.py icin shell-injection guvenlik testleri.

Bu testler _assert_safe_for_shell()'in gecen ve gecmeyen karakterleri
dogru ayirt ettigini garanti eder. Blacklist genisletildiginde (bu
oturumda oldugu gibi) burada regresyon yakalanir.
"""
import pytest

from context_automator.restore.ide_launcher import (
    _assert_safe_for_shell,
    UnsafePathError,
)


class TestShellSafety:
    @pytest.mark.parametrize("safe_path", [
        r"C:\Users\bdogan\Projects\demo",
        r"C:\Users\bdogan\Projects\my-project_v2",
        r"C:\Program Files\Cursor\cursor.cmd",
    ])
    def test_safe_paths_pass(self, safe_path):
        _assert_safe_for_shell(safe_path, "test")

    @pytest.mark.parametrize("char", list('"&|^<>%!(),;`'))
    def test_each_dangerous_character_is_rejected(self, char):
        value = f"C:\\Users\\bdogan\\evil{char}path"
        with pytest.raises(UnsafePathError):
            _assert_safe_for_shell(value, "test")

    def test_newline_is_rejected(self):
        # Onceki blacklist'te eksikti -- komut satiri enjeksiyonuna acik
        # bir yuzeydi (multi-line cmd.exe komutlari).
        with pytest.raises(UnsafePathError):
            _assert_safe_for_shell("C:\\Users\\bdogan\\evil\npath", "test")

    def test_error_message_names_the_bad_characters(self):
        with pytest.raises(UnsafePathError) as exc_info:
            _assert_safe_for_shell("C:\\evil&path", "working_dir")
        assert "working_dir" in str(exc_info.value)
        assert "&" in str(exc_info.value)
