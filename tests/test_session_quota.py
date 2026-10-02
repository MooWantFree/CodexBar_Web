import json
from copy import deepcopy

import pytest

from codex_token_report.db import Database
from codex_token_report.scanner import SessionScanner
from codex_token_report.session_quota import (
    SessionQuotaHistory,
    finalize_quota_samples,
    quota_candidates,
)


def quota_row(*, timestamp="2026-10-02T10:00:00Z", used=81):
    return {
        "type": "event_msg", "timestamp": timestamp,
        "payload": {
            "type": "token_count", "info": None,
            "rate_limits": {
                "limit_id": "codex", "limit_name": None, "plan_type": "prolite",
                "primary": {"used_percent": used, "window_minutes": 10080,
                            "resets_at": 1791062171},
                "secondary": None,
                "credits": {"balance": "secret"},
                "credential": "secret",
            },
            "prompt": "private conversation content",
        },
    }


def samples(row, *, source="active.jsonl", line=10, session="session-1"):
    return finalize_quota_samples(
        quota_candidates(row, source_file=source, line_number=line), session_id=session,
    )


def test_allowlisted_metadata_is_archived_without_usage_or_private_payload(tmp_path):
    archive = SessionQuotaHistory(Database(tmp_path / "history.sqlite"))
    assert archive.store(samples(quota_row())) == 1
    result = archive.records("session-1")
    assert result["scope"] == "account_wide_observed_in_sessions"
    assert result["total"] == 1
    observed = result["samples"][0]
    assert observed["used_percent"] == 81
    assert observed["resets_at"] == "2026-10-03T21:16:11+00:00"
    assert observed["source_kind"] == "session_log"
    assert "secret" not in str(result)
    assert "private conversation content" not in str(result)
    assert "input_tokens" not in observed
    assert "account_key" not in observed


def test_idempotent_after_source_move_and_line_renumbering(tmp_path):
    archive = SessionQuotaHistory(Database(tmp_path / "history.sqlite"))
    original = samples(quota_row())
    moved = samples(quota_row(), source="archived/other.jsonl", line=1)
    assert original[0]["observation_id"] == moved[0]["observation_id"]
    assert archive.store(original) == 1
    assert archive.store(moved) == 0
    assert archive.records()["total"] == 1


def test_truncation_and_empty_scan_preserve_earlier_observations(tmp_path):
    archive = SessionQuotaHistory(Database(tmp_path / "history.sqlite"))
    archive.store(samples(quota_row()))
    archive.store(samples(quota_row(timestamp="2026-10-02T10:05:00Z", used=82)))
    archive.store([])
    # A restarted dashboard opens the same local database after logs are gone.
    restarted = SessionQuotaHistory(Database(tmp_path / "history.sqlite"))
    assert restarted.records()["total"] == 2


def test_copied_subagent_history_and_unknown_sessions_are_not_assigned():
    candidates = quota_candidates(quota_row(), source_file="a.jsonl", line_number=10)
    assert finalize_quota_samples(candidates, session_id=None) == []
    assert finalize_quota_samples(
        candidates, session_id="agent", is_subagent=True, history_start_ordinal=11,
    ) == []
    assert len(finalize_quota_samples(
        candidates, session_id="agent", is_subagent=True, history_start_ordinal=10,
    )) == 1


@pytest.mark.parametrize("field,value", [
    ("used_percent", -1), ("used_percent", 101), ("used_percent", float("nan")),
    ("used_percent", True), ("window_minutes", 0), ("window_minutes", float("inf")),
    ("resets_at", -1), ("resets_at", 10**100),
])
def test_malformed_window_is_ignored(field, value):
    row = quota_row()
    row["payload"]["rate_limits"]["primary"][field] = value
    assert samples(row) == []


def test_secondary_window_and_different_sessions_keep_distinct_samples(tmp_path):
    archive = SessionQuotaHistory(Database(tmp_path / "history.sqlite"))
    row = quota_row()
    row["payload"]["rate_limits"]["secondary"] = deepcopy(
        row["payload"]["rate_limits"]["primary"]
    )
    archive.store(samples(row))
    archive.store(samples(row, session="session-2"))
    assert archive.records()["total"] == 4
    page = archive.records("session-1", offset=0, limit=1)
    assert page["total"] == 2 and page["has_more"]
    assert archive.records("missing")["total"] == 0


def test_valid_older_window_is_preserved_with_unknown_limit_identity():
    row = quota_row()
    del row["payload"]["rate_limits"]["limit_id"]
    assert samples(row)[0]["limit_id"] == "unknown"


def test_descendant_filter_paginates_globally_and_empty_filter_matches_nothing(tmp_path):
    archive = SessionQuotaHistory(Database(tmp_path / "history.sqlite"))
    for session in ("parent", "child", "unrelated"):
        archive.store(samples(quota_row(), session=session))
    result = archive.records(session_ids={"parent", "child"}, limit=1)
    assert result["total"] == 2
    assert result["has_more"] is True
    assert result["samples"][0]["session_id"] in {"parent", "child"}
    assert archive.records(session_ids=[])["total"] == 0
    assert archive.records(session_ids=["parent", "parent"])["total"] == 1
    with pytest.raises(ValueError):
        archive.records("parent", session_ids=["child"])


def test_scanner_archives_quota_only_events_and_preserves_samples_after_clear_and_move(tmp_path):
    codex_home = tmp_path / ".codex"
    sessions = codex_home / "sessions"
    sessions.mkdir(parents=True)
    source = sessions / "rollout.jsonl"
    header = {"type": "session_meta", "payload": {"id": "session-1"}}
    source.write_text(
        "\n".join(json.dumps(row) for row in (header, quota_row())) + "\n", encoding="utf-8",
    )
    database = Database(tmp_path / "history.sqlite")
    scanner = SessionScanner(codex_home=codex_home, database=database, timezone="Asia/Taipei")
    assert scanner.scan().stored_events == 0
    assert scanner.session_quota.records("session-1")["total"] == 1
    with source.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(quota_row(timestamp="2026-10-02T10:05:00Z", used=82)) + "\n")
    scanner.scan()
    assert scanner.session_quota.records("session-1")["total"] == 2
    archived = codex_home / "archived_sessions"
    archived.mkdir()
    source = source.rename(archived / "moved.jsonl")
    scanner.scan()
    assert scanner.session_quota.records("session-1")["total"] == 2
    # The same source can be truncated to a fragment without its original header.
    source.write_text(
        json.dumps(quota_row(timestamp="2026-10-02T10:10:00Z", used=83)) + "\n",
        encoding="utf-8",
    )
    scanner.scan()
    assert scanner.session_quota.records("session-1")["total"] == 3
    source.unlink()
    restarted = SessionScanner(codex_home=codex_home, database=database, timezone="Asia/Taipei")
    restarted.scan()
    assert restarted.session_quota.records("session-1")["total"] == 3


@pytest.mark.parametrize("offset,limit", [(-1, 1), (0, 0), (True, 1), (0, False)])
def test_pagination_validation(tmp_path, offset, limit):
    archive = SessionQuotaHistory(Database(tmp_path / "history.sqlite"))
    with pytest.raises(ValueError):
        archive.records(offset=offset, limit=limit)
