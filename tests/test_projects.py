from pathlib import Path

from codex_token_report.projects import ProjectResolver


def test_project_resolver_merges_subdirectories_and_worktrees(tmp_path: Path) -> None:
    repository = tmp_path / "main-project"
    git_dir = repository / ".git"
    nested = repository / "src" / "feature"
    worktree = tmp_path / "managed-worktree"
    worktree_git_dir = git_dir / "worktrees" / "managed-worktree"
    nested.mkdir(parents=True)
    worktree.mkdir()
    worktree_git_dir.mkdir(parents=True)
    (worktree_git_dir / "commondir").write_text("../..", encoding="utf-8")
    (worktree / ".git").write_text(f"gitdir: {worktree_git_dir}\n", encoding="utf-8")

    resolver = ProjectResolver()
    nested_result = resolver.resolve(
        {"cwd": str(nested), "workspace_roots": [str(repository)]}
    )
    worktree_result = resolver.resolve(
        {"cwd": str(worktree), "workspace_roots": [str(worktree)]}
    )

    assert nested_result is not None
    assert worktree_result is not None
    assert Path(nested_result.path) == repository.resolve()
    assert Path(worktree_result.path) == repository.resolve()
    assert nested_result.key == worktree_result.key


def test_project_resolver_falls_back_to_workspace_root(tmp_path: Path) -> None:
    workspace = tmp_path / "plain-workspace"
    workspace.mkdir()

    result = ProjectResolver().resolve(
        {"cwd": str(workspace / "subdirectory"), "workspace_roots": [str(workspace)]}
    )

    assert result is not None
    assert Path(result.path) == workspace.resolve()
