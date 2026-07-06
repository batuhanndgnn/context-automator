"""capture/git_state.py icin testler -- gercek bir gecici git deposu
uzerinde calisir (git CLI'nin makinede kurulu oldugunu varsayar).
"""
import subprocess

import pytest

from context_automator.capture.git_state import capture_git_state


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True,
                    capture_output=True, text=True)


@pytest.fixture
def git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-b", "main", cwd=repo)
    _git("config", "user.email", "test@example.com", cwd=repo)
    _git("config", "user.name", "Test User", cwd=repo)
    (repo / "README.md").write_text("hello", encoding="utf-8")
    _git("add", "README.md", cwd=repo)
    _git("commit", "-m", "initial", cwd=repo)
    return repo


class TestCaptureGitState:
    def test_clean_repo_reports_not_dirty(self, git_repo):
        state = capture_git_state(git_repo)
        assert state.available is True
        assert state.dirty is False
        assert state.branch == "main"

    def test_dirty_repo_is_detected(self, git_repo):
        (git_repo / "README.md").write_text("changed", encoding="utf-8")
        state = capture_git_state(git_repo)
        assert state.available is True
        assert state.dirty is True

    def test_nonexistent_directory_is_unavailable(self, tmp_path):
        state = capture_git_state(tmp_path / "does-not-exist")
        assert state.available is False
        assert state.error is not None

    def test_non_git_directory_is_unavailable(self, tmp_path):
        plain = tmp_path / "not-a-repo"
        plain.mkdir()
        state = capture_git_state(plain)
        assert state.available is False

    def test_stash_count_reflects_stash_list(self, git_repo):
        (git_repo / "README.md").write_text("changed again", encoding="utf-8")
        _git("stash", "push", "-m", "test stash", cwd=git_repo)
        state = capture_git_state(git_repo)
        assert state.stash_count == 1
        # stash sonrasi working tree tekrar temiz olmali
        assert state.dirty is False
