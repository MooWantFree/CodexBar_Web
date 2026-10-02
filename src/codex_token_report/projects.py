from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ProjectIdentity:
    key: str
    path: str
    workspace_root: str
    working_directory: str


class ProjectResolver:
    def __init__(self) -> None:
        self._cache: dict[tuple[str, tuple[str, ...]], ProjectIdentity | None] = {}

    @staticmethod
    def _normalized_path(value: str) -> str:
        return os.path.abspath(os.path.normpath(os.path.expanduser(value)))

    @staticmethod
    def _contains(root: str, child: str) -> bool:
        try:
            return os.path.commonpath(
                [os.path.normcase(root), os.path.normcase(child)]
            ) == os.path.normcase(root)
        except ValueError:
            return False

    def _workspace_root(self, cwd: str, roots: list[str]) -> str:
        normalized_roots = [self._normalized_path(root) for root in roots if root]
        containing = [root for root in normalized_roots if self._contains(root, cwd)]
        if containing:
            return max(containing, key=len)
        return normalized_roots[0] if normalized_roots else cwd

    @staticmethod
    def _git_root(candidate: str) -> str | None:
        path = Path(candidate)
        if not path.exists():
            return None
        if path.is_file():
            path = path.parent
        for directory in (path, *path.parents):
            marker = directory / ".git"
            if marker.is_dir():
                return str(directory.resolve())
            if not marker.is_file():
                continue
            try:
                line = marker.read_text(encoding="utf-8", errors="replace").strip()
                if not line.lower().startswith("gitdir:"):
                    return str(directory.resolve())
                git_dir = Path(line.split(":", 1)[1].strip())
                if not git_dir.is_absolute():
                    git_dir = (directory / git_dir).resolve()
                common_file = git_dir / "commondir"
                if common_file.is_file():
                    common = Path(common_file.read_text(encoding="utf-8").strip())
                    if not common.is_absolute():
                        common = (git_dir / common).resolve()
                    if common.name.lower() == ".git":
                        return str(common.parent)
                parts = [part.lower() for part in git_dir.parts]
                if "worktrees" in parts:
                    index = parts.index("worktrees")
                    common = Path(*git_dir.parts[:index])
                    if common.name.lower() == ".git":
                        return str(common.parent)
                return str(directory.resolve())
            except OSError:
                return str(directory.resolve())
        return None

    def resolve(self, payload: dict[str, Any]) -> ProjectIdentity | None:
        cwd_value = str(payload.get("cwd") or "").strip()
        roots_value = payload.get("workspace_roots") or []
        roots = [str(root).strip() for root in roots_value if str(root).strip()]
        if not cwd_value and not roots:
            return None
        cwd = self._normalized_path(cwd_value or roots[0])
        cache_key = (cwd, tuple(roots))
        if cache_key in self._cache:
            return self._cache[cache_key]
        workspace_root = self._workspace_root(cwd, roots)
        project_path = self._git_root(workspace_root) or workspace_root
        project_path = self._normalized_path(project_path)
        identity = ProjectIdentity(
            key=os.path.normcase(project_path).replace("\\", "/"),
            path=project_path,
            workspace_root=workspace_root,
            working_directory=cwd,
        )
        self._cache[cache_key] = identity
        return identity
