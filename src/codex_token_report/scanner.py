from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from contextlib import closing
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .db import Database
from .projects import ProjectIdentity, ProjectResolver
from .session_quota import SessionQuotaHistory, finalize_quota_samples, quota_candidates
from .tiers import PriorityTraceScanner

SCANNER_PARSER_VERSION = "5"
PREFIX_ANCHOR_BYTES = 4096


@dataclass(slots=True)
class ScanResult:
    started_at: str
    finished_at: str
    discovered_files: int
    scanned_files: int
    unchanged_files: int
    stored_events: int
    parse_errors: int
    missing_directories: list[str]
    priority_trace: dict[str, Any]
    tier_counts: dict[str, int]
    incremental_files: int = 0
    skipped_copied_events: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ParserState:
    session_id: str | None = None
    parent_session_id: str | None = None
    is_subagent: bool = False
    subagent_history_start_ordinal: int | None = None
    current_model: str | None = None
    current_project: ProjectIdentity | None = None
    model_by_turn: dict[str, str] = field(default_factory=dict)
    project_by_turn: dict[str, ProjectIdentity] = field(default_factory=dict)
    line_number: int = 0
    prefix_anchor: str | None = None

    def to_json(self) -> str:
        payload = asdict(self)
        return json.dumps(payload, separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_json(cls, value: str | None) -> ParserState | None:
        if not value:
            return None
        try:
            payload = json.loads(value)
            current_project = payload.get("current_project")
            project_by_turn = payload.get("project_by_turn") or {}
            return cls(
                session_id=payload.get("session_id"),
                parent_session_id=payload.get("parent_session_id"),
                is_subagent=bool(payload.get("is_subagent")),
                subagent_history_start_ordinal=payload.get(
                    "subagent_history_start_ordinal"
                ),
                current_model=payload.get("current_model"),
                current_project=(
                    ProjectIdentity(**current_project) if current_project else None
                ),
                model_by_turn={
                    str(key): str(model)
                    for key, model in (payload.get("model_by_turn") or {}).items()
                },
                project_by_turn={
                    str(key): ProjectIdentity(**project)
                    for key, project in project_by_turn.items()
                },
                line_number=int(payload.get("line_number") or 0),
                prefix_anchor=payload.get("prefix_anchor"),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None


@dataclass(slots=True)
class ParsedFile:
    events: list[dict[str, Any]]
    parse_errors: int
    state: ParserState
    parser_mode: str
    append_safe: bool
    size_bytes: int
    requires_full_rescan: bool = False
    skipped_copied_events: int = 0
    superseded_events: list[dict[str, Any]] = field(default_factory=list)
    quota_samples: list[dict[str, Any]] = field(default_factory=list)


class SessionScanner:
    def _scan_titles(self) -> None:
        # Titles are metadata; never derive them from user/assistant message bodies.
        titles = {}
        metadata = {}
        index = self.codex_home / "session_index.jsonl"
        try:
            with index.open(encoding="utf-8") as stream:
                for line in stream:
                    try:
                        row = json.loads(line)
                        identity = row.get("id") or row.get("thread_id")
                        title = row.get("thread_name") or row.get("title")
                        if isinstance(identity, str) and isinstance(title, str) and title.strip():
                            titles[identity] = title.strip()[:500]
                    except (ValueError, AttributeError):
                        continue
        except (OSError, UnicodeError):
            pass
        for path in sorted(self.codex_home.glob("state_*.sqlite"), reverse=True):
            try:
                with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as source:
                    for identity, title in source.execute("SELECT id, title FROM threads"):
                        if isinstance(title, str) and title.strip():
                            titles.setdefault(str(identity), title.strip()[:500])
                    # Older state databases have titles without source metadata. A
                    # missing or malformed relationship must not prevent title import.
                    try:
                        columns = {
                            row[1] for row in source.execute("PRAGMA table_info(threads)")
                        }
                        if "source" not in columns:
                            continue
                        parent_column = (
                            "parent_thread_id" if "parent_thread_id" in columns else "NULL"
                        )
                        for identity, origin, parent in source.execute(
                            f"SELECT id, source, {parent_column} FROM threads"
                        ):
                            if isinstance(identity, str) and identity.strip():
                                relationship = self._session_relationship(
                                    {"source": origin, "parent_thread_id": parent}, identity
                                )
                                known = metadata.setdefault(identity, relationship)
                                known["parent_session_id"] = (
                                    known["parent_session_id"]
                                    or relationship["parent_session_id"]
                                )
                                known["is_subagent"] |= relationship["is_subagent"]
                    except (sqlite3.Error, ValueError, TypeError):
                        pass
            except (sqlite3.Error, OSError):
                continue
        self.database.save_session_titles(titles)
        self.database.save_session_metadata(metadata)

    def __init__(self, *, codex_home: Path, database: Database, timezone: str) -> None:
        self.codex_home = codex_home
        self.database = database
        self.timezone = ZoneInfo(timezone)
        self.priority_trace = PriorityTraceScanner(codex_home=codex_home, database=database)
        self.session_quota = SessionQuotaHistory(database)
        self.projects = ProjectResolver()
        self._lock = threading.Lock()
        self.database.prepare_scanner_version(SCANNER_PARSER_VERSION)

    def _session_files(self) -> tuple[list[Path], list[str]]:
        paths: list[Path] = []
        missing: list[str] = []
        for name in ("sessions", "archived_sessions"):
            directory = self.codex_home / name
            if not directory.exists():
                missing.append(str(directory))
                continue
            paths.extend(directory.rglob("*.jsonl"))
        return sorted(paths), missing

    @staticmethod
    def _integer(payload: Any, key: str) -> int:
        try:
            return max(0, int(payload.get(key, 0) or 0))
        except (AttributeError, TypeError, ValueError):
            return 0

    @staticmethod
    def _ordinal(value: Any, fallback: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return fallback

    @staticmethod
    def _is_subagent_source(value: Any) -> bool:
        if isinstance(value, str):
            if value.lstrip().startswith(("{", "[")):
                try:
                    return SessionScanner._is_subagent_source(json.loads(value))
                except (ValueError, TypeError):
                    return False
            return value.casefold() == "subagent"
        if isinstance(value, dict):
            return any(
                str(key).casefold() == "subagent"
                or SessionScanner._is_subagent_source(child)
                for key, child in value.items()
            )
        if isinstance(value, list):
            return any(SessionScanner._is_subagent_source(item) for item in value)
        return False

    @staticmethod
    def _session_relationship(payload: dict[str, Any], session_id: str) -> dict[str, Any]:
        source = payload.get("source")
        if isinstance(source, str):
            try:
                source = json.loads(source)
            except (ValueError, TypeError):
                pass
        candidates = [payload.get("parent_thread_id")]
        if isinstance(source, dict):
            subagent = source.get("subagent")
            if isinstance(subagent, dict):
                spawn = subagent.get("thread_spawn")
                if isinstance(spawn, dict):
                    candidates.insert(0, spawn.get("parent_thread_id"))
        parent = next(
            (
                value.strip()
                for value in candidates
                if isinstance(value, str)
                and value.strip()
                and value.strip().casefold() != session_id.casefold()
            ),
            None,
        )
        # forked_from_id describes ordinary conversation forks as well as agents;
        # only an explicit parent_thread_id establishes ownership.
        return {
            "parent_session_id": parent,
            "is_subagent": bool(parent or SessionScanner._is_subagent_source(source)),
        }

    def _parse_timestamp(self, value: str) -> datetime:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed

    @staticmethod
    def _prefix_anchor(path: Path, end_offset: int) -> str:
        start = max(0, end_offset - PREFIX_ANCHOR_BYTES)
        with path.open("rb") as stream:
            stream.seek(start)
            data = stream.read(end_offset - start)
        return hashlib.sha256(data).hexdigest()

    def _prefix_matches(
        self, path: Path, *, end_offset: int, expected_anchor: str | None
    ) -> bool:
        if not expected_anchor:
            return False
        try:
            return self._prefix_anchor(path, end_offset) == expected_anchor
        except OSError:
            return False

    def _candidate(
        self,
        *,
        row: dict[str, Any],
        payload: dict[str, Any],
        usage: dict[str, Any],
        source_kind: str,
        state: ParserState,
        line_number: int,
    ) -> dict[str, Any] | None:
        if usage.get("input_tokens") is None:
            return None
        timestamp_value = str(row.get("timestamp") or "")
        try:
            timestamp = self._parse_timestamp(timestamp_value)
        except ValueError:
            return None

        turn_id = str(payload.get("turn_id") or "") or None
        response_id = str(payload.get("response_id") or "") or None
        model = state.current_model
        project = state.current_project
        if turn_id:
            model = state.model_by_turn.get(turn_id, model)
            project = state.project_by_turn.get(turn_id, project)

        input_tokens = self._integer(usage, "input_tokens")
        cached_tokens = max(
            self._integer(usage, "cached_input_tokens"),
            self._integer(usage, "cache_read_input_tokens"),
        )
        cached_tokens = min(cached_tokens, input_tokens)
        output_tokens = self._integer(usage, "output_tokens")
        reasoning_tokens = min(
            self._integer(usage, "reasoning_output_tokens"), output_tokens
        )
        total_tokens = self._integer(usage, "total_tokens")
        if not total_tokens:
            total_tokens = input_tokens + output_tokens
        ordinal = self._ordinal(row.get("ordinal"), line_number)

        return {
            "source_kind": source_kind,
            "timestamp_utc": timestamp.astimezone(UTC).isoformat(),
            "local_date": timestamp.astimezone(self.timezone).date().isoformat(),
            "model": model,
            "turn_id": turn_id,
            "response_id": response_id,
            "ordinal": ordinal,
            "input_tokens": input_tokens,
            "cached_input_tokens": cached_tokens,
            "cache_write_input_tokens": self._integer(
                usage, "cache_write_input_tokens"
            ),
            "output_tokens": output_tokens,
            "reasoning_output_tokens": reasoning_tokens,
            "total_tokens": total_tokens,
            "service_tier": "unknown",
            "tier_source": None,
            "pricing_model": model,
            "project_key": project.key if project else None,
            "project_path": project.path if project else None,
            "workspace_root": project.workspace_root if project else None,
            "working_directory": project.working_directory if project else None,
            "_timestamp_value": timestamp_value,
        }

    def _accept_session_meta(
        self,
        payload: dict[str, Any],
        state: ParserState,
        *,
        incremental: bool,
    ) -> bool:
        session_id = str(payload.get("id") or payload.get("session_id") or "") or None
        relationship = self._session_relationship(payload, session_id or "")
        cutoff_value = payload.get("subagent_history_start_ordinal")
        cutoff = None
        if cutoff_value is not None:
            try:
                cutoff = int(cutoff_value)
            except (TypeError, ValueError):
                cutoff = None

        if state.session_id:
            return False
        state.session_id = session_id
        state.parent_session_id = relationship["parent_session_id"]
        state.is_subagent = relationship["is_subagent"]
        state.subagent_history_start_ordinal = cutoff
        return incremental and session_id is not None

    def _finalize_candidates(
        self,
        candidates: list[dict[str, Any]],
        *,
        source_file: str,
        state: ParserState,
    ) -> tuple[list[dict[str, Any]], int]:
        events_by_id: dict[str, dict[str, Any]] = {}
        skipped = 0
        cutoff = state.subagent_history_start_ordinal
        identity_root = state.session_id or source_file
        for candidate in candidates:
            ordinal = int(candidate["ordinal"])
            if state.is_subagent and cutoff is not None and ordinal < cutoff:
                skipped += 1
                continue
            response_id = candidate["response_id"]
            identity = response_id or (
                f"{ordinal}:{candidate['_timestamp_value']}:{candidate['source_kind']}"
            )
            event_id = hashlib.sha256(f"{identity_root}|{identity}".encode()).hexdigest()
            candidate.pop("_timestamp_value", None)
            candidate.update(
                {
                    "event_id": event_id,
                    "source_file": source_file,
                    "session_id": state.session_id,
                    "is_subagent": int(state.is_subagent),
                }
            )
            events_by_id[event_id] = candidate
        return list(events_by_id.values()), skipped

    def _parse_file(
        self,
        path: Path,
        *,
        start_offset: int = 0,
        initial_state: ParserState | None = None,
        previous_mode: str = "none",
        retained_state: ParserState | None = None,
    ) -> ParsedFile:
        source_file = str(path.resolve())
        incremental = start_offset > 0
        state = initial_state or ParserState()
        usage_records: list[dict[str, Any]] = []
        fallback_records: list[dict[str, Any]] = []
        parse_errors = 0
        append_safe = True
        requires_full_rescan = False
        quota_records: list[dict[str, Any]] = []

        with path.open("rb") as stream:
            stream.seek(start_offset)
            while raw_line := stream.readline():
                state.line_number += 1
                if not raw_line.endswith(b"\n"):
                    append_safe = False
                if not raw_line.strip():
                    continue
                try:
                    row = json.loads(raw_line.decode("utf-8", errors="replace"))
                except json.JSONDecodeError:
                    parse_errors += 1
                    continue
                if not isinstance(row, dict):
                    continue
                quota_records.extend(quota_candidates(
                    row, source_file=source_file, line_number=state.line_number
                ))
                row_type = row.get("type")
                payload = row.get("payload") or {}
                if not isinstance(payload, dict):
                    continue

                if row_type == "session_meta":
                    requires_full_rescan |= self._accept_session_meta(
                        payload, state, incremental=incremental
                    )
                    continue
                if row_type == "turn_context":
                    turn_id = str(payload.get("turn_id") or "")
                    state.current_model = str(payload.get("model") or "") or None
                    state.current_project = self.projects.resolve(payload)
                    if turn_id and state.current_model:
                        state.model_by_turn[turn_id] = state.current_model
                    if turn_id and state.current_project:
                        state.project_by_turn[turn_id] = state.current_project
                    continue

                usage: Any = None
                source_kind: str | None = None
                target = usage_records
                if row_type == "token_usage_record":
                    usage = payload.get("usage")
                    source_kind = "token_usage_record"
                elif row_type == "event_msg" and payload.get("type") == "token_count":
                    usage = (payload.get("info") or {}).get("last_token_usage")
                    source_kind = "token_count_fallback"
                    target = fallback_records
                if not isinstance(usage, dict) or source_kind is None:
                    continue
                candidate = self._candidate(
                    row=row,
                    payload=payload,
                    usage=usage,
                    source_kind=source_kind,
                    state=state,
                    line_number=state.line_number,
                )
                if candidate is None:
                    if usage.get("input_tokens") is not None:
                        parse_errors += 1
                    continue
                target.append(candidate)
            end_offset = stream.tell()

        state.prefix_anchor = self._prefix_anchor(path, end_offset)
        if state.session_id is None and retained_state is not None:
            # A cleared or tail-only rollout may have lost session_meta. Retain
            # its confirmed ownership; explicit new metadata always wins.
            state.session_id = retained_state.session_id
            state.parent_session_id = retained_state.parent_session_id
            state.is_subagent = retained_state.is_subagent
            state.subagent_history_start_ordinal = (
                retained_state.subagent_history_start_ordinal
            )

        if incremental and previous_mode == "fallback" and usage_records:
            requires_full_rescan = True
        if previous_mode == "records" or usage_records:
            selected = usage_records
            parser_mode = "records"
        elif previous_mode == "fallback" or fallback_records:
            selected = fallback_records
            parser_mode = "fallback"
        else:
            selected = []
            parser_mode = previous_mode if previous_mode != "none" else "none"

        events, skipped = self._finalize_candidates(
            selected, source_file=source_file, state=state
        )
        superseded = []
        if parser_mode == "records":
            fallbacks, _ = self._finalize_candidates(
                fallback_records, source_file=source_file, state=state
            )
            superseded = fallbacks
        return ParsedFile(
            events=events,
            parse_errors=parse_errors,
            state=state,
            parser_mode=parser_mode,
            append_safe=append_safe,
            size_bytes=end_offset,
            requires_full_rescan=requires_full_rescan,
            skipped_copied_events=skipped,
            superseded_events=superseded,
            quota_samples=finalize_quota_samples(
                quota_records, session_id=state.session_id,
                is_subagent=state.is_subagent,
                history_start_ordinal=state.subagent_history_start_ordinal,
            ),
        )

    def parse_file(self, path: Path) -> tuple[list[dict[str, Any]], int]:
        parsed = self._parse_file(path)
        return parsed.events, parsed.parse_errors

    def scan(self) -> ScanResult:
        with self._lock:
            started = datetime.now(UTC)
            files, missing = self._session_files()
            scanned = 0
            unchanged = 0
            incremental_files = 0
            stored = 0
            parse_errors = 0
            skipped_copied_events = 0

            for path in files:
                try:
                    stat = path.stat()
                except OSError:
                    parse_errors += 1
                    continue
                source_file = str(path.resolve())
                if self.database.file_is_current(source_file, stat.st_mtime_ns, stat.st_size):
                    unchanged += 1
                    continue

                old_state = (
                    self.database.get_file_state(source_file)
                    or self.database.get_moved_file_state(source_file)
                )
                retained_state = (
                    ParserState.from_json(old_state["parser_state_json"])
                    if old_state else None
                )
                can_append = bool(
                    old_state
                    and old_state["append_safe"]
                    and stat.st_size > int(old_state["size_bytes"])
                )
                parser_state = (
                    ParserState.from_json(old_state["parser_state_json"])
                    if can_append and old_state
                    else None
                )
                can_append = bool(
                    can_append
                    and parser_state is not None
                    and self._prefix_matches(
                        path,
                        end_offset=int(old_state["size_bytes"]),
                        expected_anchor=parser_state.prefix_anchor,
                    )
                )
                try:
                    if can_append and old_state and parser_state:
                        parsed = self._parse_file(
                            path,
                            start_offset=int(old_state["size_bytes"]),
                            initial_state=parser_state,
                            previous_mode=str(old_state["parser_mode"]),
                        )
                        if parsed.requires_full_rescan:
                            parsed = self._parse_file(path, retained_state=retained_state)
                            can_append = False
                    else:
                        parsed = self._parse_file(path, retained_state=retained_state)
                except OSError:
                    parse_errors += 1
                    continue

                try:
                    observed_stat = path.stat()
                except OSError:
                    parse_errors += 1
                    continue

                scanned += 1
                parse_errors += parsed.parse_errors
                skipped_copied_events += parsed.skipped_copied_events
                scanned_at = datetime.now(UTC).isoformat()
                state_json = parsed.state.to_json()
                if parsed.state.session_id:
                    self.database.save_session_metadata(
                        {
                            parsed.state.session_id: {
                                "parent_session_id": parsed.state.parent_session_id,
                                "is_subagent": parsed.state.is_subagent,
                            }
                        }
                    )
                self.session_quota.store(parsed.quota_samples)
                if can_append and old_state:
                    incremental_files += 1
                    cumulative_errors = int(old_state["parse_errors"]) + parsed.parse_errors
                    stored += self.database.append_file_events(
                        source_file=source_file,
                        session_id=parsed.state.session_id,
                        mtime_ns=observed_stat.st_mtime_ns,
                        size_bytes=parsed.size_bytes,
                        events=parsed.events,
                        parse_errors=cumulative_errors,
                        scanned_at=scanned_at,
                        parser_mode=parsed.parser_mode,
                        parser_state_json=state_json,
                        append_safe=parsed.append_safe,
                        superseded_events=parsed.superseded_events,
                        copied_history_before_ordinal=(
                            parsed.state.subagent_history_start_ordinal
                            if parsed.state.is_subagent else None
                        ),
                    )
                else:
                    stored += self.database.replace_file_events(
                        source_file=source_file,
                        session_id=parsed.state.session_id,
                        mtime_ns=observed_stat.st_mtime_ns,
                        size_bytes=parsed.size_bytes,
                        events=parsed.events,
                        parse_errors=parsed.parse_errors,
                        scanned_at=scanned_at,
                        parser_mode=parsed.parser_mode,
                        parser_state_json=state_json,
                        append_safe=parsed.append_safe,
                        superseded_events=parsed.superseded_events,
                        copied_history_before_ordinal=(
                            parsed.state.subagent_history_start_ordinal
                            if parsed.state.is_subagent else None
                        ),
                    )

            trace = self.priority_trace.scan()
            if trace.available:
                tier_counts = self.database.classify_service_tiers(
                    source_path=trace.source_path,
                    coverage_start_utc=trace.coverage_start_utc,
                    coverage_end_utc=trace.coverage_end_utc,
                )
            else:
                stats = self.database.storage_stats()
                tier_counts = {
                    "standard": stats["standard_events"],
                    "priority": stats["priority_events"],
                    "unknown": stats["unknown_events"],
                }

            finished = datetime.now(UTC)
            result = ScanResult(
                started_at=started.isoformat(),
                finished_at=finished.isoformat(),
                discovered_files=len(files),
                scanned_files=scanned,
                unchanged_files=unchanged,
                stored_events=stored,
                parse_errors=parse_errors,
                missing_directories=missing,
                priority_trace=trace.to_dict(),
                tier_counts=tier_counts,
                incremental_files=incremental_files,
                skipped_copied_events=skipped_copied_events,
            )
            self.database.set_metadata("last_scan", json.dumps(result.to_dict()))
            self.database.capture_price_snapshots()
            self._scan_titles()
            return result
