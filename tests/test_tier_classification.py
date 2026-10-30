from pathlib import Path
from typing import Any

import pytest

from codex_token_report.db import Database


def _event(event_id: str, **overrides: Any) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "source_file": "rollout.jsonl",
        "source_kind": "token_usage_record",
        "timestamp_utc": "2026-09-20T00:30:00+00:00",
        "local_date": "2026-09-20",
        "model": "event-model",
        "turn_id": event_id,
        "response_id": f"response-{event_id}",
        "input_tokens": 10,
        "cached_input_tokens": 0,
        "cache_write_input_tokens": 0,
        "output_tokens": 1,
        "reasoning_output_tokens": 0,
        "total_tokens": 11,
        "service_tier": "unknown",
        "tier_source": None,
        "pricing_model": "event-model",
        **overrides,
    }


def _database(tmp_path: Path, events: list[dict[str, Any]]) -> Database:
    database = Database(tmp_path / "usage.sqlite3")
    database.replace_file_events(
        source_file="rollout.jsonl", mtime_ns=1, size_bytes=1, events=events,
        parse_errors=0, scanned_at="2026-09-20T06:00:00+00:00",
    )
    # Auditing writes catches a no-op UPDATE even if its stored values match.
    with database.connect() as connection:
        connection.executescript(
            """
            CREATE TABLE classification_updates(event_id TEXT NOT NULL);
            CREATE TRIGGER audit_classification_update AFTER UPDATE ON usage_events
            BEGIN
                INSERT INTO classification_updates VALUES (NEW.event_id);
            END;
            """
        )
    return database


def _save_trace(
    database: Database,
    *,
    source: str = "logs_2.sqlite",
    turn_id: str | None = None,
    tier: str = "priority",
    model: str | None = "trace-model",
    row_id: int = 1,
    coverage: tuple[str, str] | None = None,
) -> None:
    turns = [] if turn_id is None else [{
        "source_path": source,
        "turn_id": turn_id,
        "thread_id": None,
        "pricing_model": model,
        "requested_tier": tier,
        "trace_timestamp_utc": "2026-09-20T00:30:00+00:00",
        "source_row_id": row_id,
    }]
    database.save_priority_trace(
        source_path=source, source_identity="generation-1", last_row_id=row_id,
        coverage_start_utc=coverage[0] if coverage else None,
        coverage_end_utc=coverage[1] if coverage else None,
        scanned_at="2026-09-20T06:00:00+00:00", turns=turns, reset=False,
    )


def _classify(database: Database, source: str = "logs_2.sqlite") -> dict[str, int]:
    return database.classify_service_tiers(
        source_path=source, coverage_start_utc=None, coverage_end_utc=None,
    )


def _classifications(database: Database) -> dict[str, tuple[str, str | None, str | None]]:
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT event_id, service_tier, tier_source, pricing_model FROM usage_events"
        )
        return {row[0]: tuple(row)[1:] for row in rows}


def _take_updates(database: Database) -> list[str]:
    with database.connect() as connection:
        result = [row[0] for row in connection.execute(
            "SELECT event_id FROM classification_updates ORDER BY event_id"
        )]
        connection.execute("DELETE FROM classification_updates")
    return result


@pytest.mark.parametrize("model", [None, "", "event-model"])
@pytest.mark.parametrize("trace_model", [None, "", "trace-model"])
def test_repeated_classification_does_not_update_events(
    tmp_path: Path, model: str | None, trace_model: str | None,
) -> None:
    database = _database(tmp_path, [
        _event("unknown", turn_id=None, model=None, pricing_model=None),
        _event("covered"),
        _event("session", session_service_tier="priority"),
        _event("trace", session_service_tier="priority", model=model, pricing_model=model),
    ])
    _save_trace(
        database, turn_id="trace", tier="standard", model=trace_model,
        coverage=("2026-09-20T00:00:00+00:00", "2026-09-20T01:00:00+00:00"),
    )

    assert _classify(database) == {"standard": 2, "priority": 1, "unknown": 1}
    assert _classifications(database) == {
        "unknown": ("unknown", None, None),
        "covered": ("standard", "logs_2_absence", "event-model"),
        "session": ("priority", "session_settings", "event-model"),
        "trace": ("standard", "logs_2_request", trace_model if trace_model is not None else model),
    }
    assert _take_updates(database) == ["covered", "session", "trace"]

    assert _classify(database) == {"standard": 2, "priority": 1, "unknown": 1}
    assert _take_updates(database) == []


def test_late_trace_corrects_historical_tier_and_pricing_model(tmp_path: Path) -> None:
    database = _database(tmp_path, [
        _event("historical", session_service_tier="standard"),
        _event("unchanged", session_service_tier="priority"),
    ])
    _classify(database)
    _take_updates(database)

    _save_trace(database, turn_id="historical", tier="priority", model="requested-model")
    assert _classify(database) == {"standard": 0, "priority": 2, "unknown": 0}
    assert _classifications(database)["historical"] == (
        "priority", "logs_2_request", "requested-model",
    )
    assert _take_updates(database) == ["historical"]

    # A later explicit standard request wins over the previous priority trace.
    _save_trace(database, turn_id="historical", tier="standard", row_id=2)
    assert _classify(database) == {"standard": 1, "priority": 1, "unknown": 0}
    assert _classifications(database)["historical"] == (
        "standard", "logs_2_request", "trace-model",
    )
    assert _take_updates(database) == ["historical"]


def test_source_switch_and_new_coverage_reclassify_history(tmp_path: Path) -> None:
    database = _database(tmp_path, [
        _event("traced"),
        _event("covered"),
        _event("gap", timestamp_utc="2026-09-20T03:00:00+00:00"),
        _event("session", session_service_tier="priority"),
    ])
    _save_trace(
        database, source="first.sqlite", turn_id="traced",
        coverage=("2026-09-20T00:00:00+00:00", "2026-09-20T01:00:00+00:00"),
    )
    assert _classify(database, "first.sqlite") == {
        "standard": 1, "priority": 2, "unknown": 1,
    }
    _take_updates(database)

    assert _classify(database, "second.sqlite") == {
        "standard": 0, "priority": 1, "unknown": 3,
    }
    assert _classifications(database)["traced"] == ("unknown", None, "event-model")
    assert _take_updates(database) == ["covered", "traced"]

    _save_trace(
        database, source="second.sqlite",
        coverage=("2026-09-20T00:00:00+00:00", "2026-09-20T01:00:00+00:00"),
    )
    _save_trace(
        database, source="second.sqlite", row_id=2,
        coverage=("2026-09-20T05:00:00+00:00", "2026-09-20T06:00:00+00:00"),
    )
    assert _classify(database, "second.sqlite") == {
        "standard": 2, "priority": 1, "unknown": 1,
    }
    assert _classifications(database)["gap"] == ("unknown", None, "event-model")
    assert _take_updates(database) == ["covered", "traced"]

    _save_trace(
        database, source="second.sqlite", row_id=3,
        coverage=("2026-09-20T02:00:00+00:00", "2026-09-20T04:00:00+00:00"),
    )
    assert _classify(database, "second.sqlite") == {
        "standard": 3, "priority": 1, "unknown": 0,
    }
    assert _take_updates(database) == ["gap"]
