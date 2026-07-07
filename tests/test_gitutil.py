"""gitutil.run_git() icin testler.

Odak noktasi: basari/basarisizlik karari SADECE returncode'a dayanmali,
git'in İngilizce/lokalize ciktisina değil (bu oturumda duzeltilen
commit_wip locale-fragility bug'inin regresyon testi).
"""
import subprocess

import pytest

from context_automator.gitutil import run_git


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


class TestRunGitSuccess:
    def test_successful_command_is_ok(self, git_repo):
        res = run_git(["git", "rev-parse", "--abbrev-ref", "HEAD"], git_repo)
        assert res.ok is True
        assert res.returncode == 0
        assert res.stdout == "main"

    def test_nonexistent_directory_returns_exc(self, tmp_path):
        res = run_git(["git", "status"], tmp_path / "does-not-exist")
        assert res.ok is False
        assert res.exc is not None


class TestRunGitFailureIsReturncodeBased:
    def test_commit_with_nothing_to_commit_is_not_ok(self, git_repo):
        """git'in "nothing to commit" gibi İngilizce metnini değil,
        SADECE returncode'u kontrol ediyoruz -- bu, locale-bağımsızlığın
        temelini oluşturuyor."""
        res = run_git(["git", "commit", "-m", "empty"], git_repo)
        assert res.ok is False
        assert res.returncode not in (0, None)

    def test_successful_commit_is_ok(self, git_repo):
        (git_repo / "file.txt").write_text("data", encoding="utf-8")
        _git("add", "file.txt", cwd=git_repo)
        res = run_git(["git", "commit", "-m", "add file"], git_repo)
        assert res.ok is True
        assert res.returncode == 0

    def test_not_a_git_repo_is_not_ok(self, tmp_path):
        plain = tmp_path / "not-a-repo"
        plain.mkdir()
        res = run_git(["git", "status"], plain)
        assert res.ok is False
        assert res.returncode != 0


class TestOutputProperty:
    def test_output_returns_stdout_on_success(self, git_repo):
        res = run_git(["git", "rev-parse", "--abbrev-ref", "HEAD"], git_repo)
        assert res.output == "main"

    def test_output_returns_stderr_on_failure(self, tmp_path):
        plain = tmp_path / "not-a-repo"
        plain.mkdir()
        res = run_git(["git", "status"], plain)
        assert res.output == res.stderr

    def test_output_is_empty_on_missing_directory(self, tmp_path):
        res = run_git(["git", "status"], tmp_path / "nope")
        assert res.output == ""
