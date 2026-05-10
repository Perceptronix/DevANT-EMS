from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


_FILE_RE = re.compile(r"(?:[A-Za-z]:)?(?:[\\/][^\s:()]+)+\.(?:py|pyi|ts|tsx|js|jsx|go|rb|java|kt|cs|cpp|c|h|rs|md|yaml|yml|json|toml|ini|cfg|sh|sql)")
_TOKEN_RE = re.compile(r"[A-Za-z0-9_./\\-]+\.(?:py|pyi|ts|tsx|js|jsx|go|rb|java|kt|cs|cpp|c|h|rs|md|yaml|yml|json|toml|ini|cfg|sh|sql)")


@dataclass
class SuspectFile:
    path: str
    score: float = 0.0
    reason: str = ""
    matched_signals: List[str] = field(default_factory=list)


class SuspectFileDetectionService:
    """Rank likely culprit files from stack trace + changed files."""

    def parse_stack_trace(self, stack_trace: str) -> List[str]:
        if not stack_trace:
            return []
        tokens = [self._normalize_path(match.group(0)) for match in _TOKEN_RE.finditer(stack_trace)]
        paths = [self._normalize_path(match.group(0)) for match in _FILE_RE.finditer(stack_trace)]
        combined = tokens + [path for path in paths if path not in tokens]
        return list(dict.fromkeys(combined))

    def rank_likely_culprit_files(
        self,
        stack_trace: str,
        changed_files: Sequence[Any],
        service_name: Optional[str] = None,
    ) -> Tuple[List[SuspectFile], float]:
        stack_files = self.parse_stack_trace(stack_trace)
        changed_paths = self._flatten_changed_files(changed_files)

        suspects: List[SuspectFile] = []
        for path in changed_paths:
            score = 0.0
            reasons: List[str] = []

            basename = self._basename(path).lower()
            if any(self._basename(stack_file).lower() == basename for stack_file in stack_files):
                score += 0.75
                reasons.append("stack_basename")
            if any(stack_file.lower() in path.lower() or path.lower() in stack_file.lower() for stack_file in stack_files):
                score += 0.45
                reasons.append("stack_path")
            if service_name and service_name.lower() in path.lower():
                score += 0.2
                reasons.append("service")

            if score > 0:
                suspects.append(
                    SuspectFile(
                        path=path,
                        score=min(1.0, score),
                        reason="+".join(reasons) or "stack_match",
                        matched_signals=stack_files,
                    )
                )

        suspects.sort(key=lambda item: item.score, reverse=True)
        if suspects:
            confidence = min(1.0, suspects[0].score)
        else:
            confidence = 0.0
        return suspects[:10], confidence

    def _flatten_changed_files(self, changed_files: Sequence[Any]) -> List[str]:
        flattened: List[str] = []
        for item in changed_files or []:
            if isinstance(item, str):
                flattened.append(item)
            elif isinstance(item, dict):
                path = item.get("path") or item.get("filename") or item.get("name")
                if isinstance(path, str):
                    flattened.append(path)
        return list(dict.fromkeys(flattened))

    def _basename(self, path: str) -> str:
        return path.replace("\\", "/").rsplit("/", 1)[-1]

    def _normalize_path(self, path: str) -> str:
        normalized = path.replace("\\", "/")
        while normalized.startswith("/"):
            normalized = normalized[1:]
        return normalized
