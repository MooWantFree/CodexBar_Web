import copy
import csv
import io
import json
import sqlite3
from contextlib import closing
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from codex_token_report.config import Settings
from codex_token_report.db import Database
from codex_token_report.main import create_app
from codex_token_report.pricing import PriceCatalog
from codex_token_report.pricing_store import PricingStore
from codex_token_report.reports import build_report, build_sessions_report
from codex_token_report.scanner import SessionScanner


def event(key, stamp="2026-09-20T01:02:03+00:00", session="one", **fields):
    return {
        "event_id": key, "session_id": session, "source_file": "fixture.jsonl",
        "source_kind": "token_usage_record", "timestamp_utc": stamp,
        "local_date": datetime.fromisoformat(stamp).astimezone(ZoneInfo("Asia/Taipei")).date().isoformat(),
        "model": "gpt-5.6-sol", "input_tokens": 100, "cached_input_tokens": 20,
        "cache_write_input_tokens": 0, "output_tokens": 10, "reasoning_output_tokens": 0,
        "total_tokens": 110, "service_tier": "priority", "turn_id": None, "response_id": None,
        "tier_source": "fixture", "pricing_model": None,
        "project_key": "e:/code/test", "project_path": "E:/Code/test", **fields,
    }


def store_events(db, events):
    db.replace_file_events(source_file="fixture.jsonl", mtime_ns=1, size_bytes=1,
                           parse_errors=0, scanned_at="2026-09-28T00:00:00+00:00", events=events)


def override(store, model="gpt-5.6-sol"):
    store.set_override(model, {"input": Decimal(100), "cached_input": Decimal(20),
                               "cache_write": None, "output": Decimal(200),
                               "api_fast_multiplier": Decimal(3)})


def test_snapshot_survives_price_changes_reparse_and_restart(tmp_path):
    db = Database(tmp_path / "usage.sqlite3")
    store = PricingStore(database=db)
    original = event("old")
    store_events(db, [original])
    old = build_report(store.prepare_events(db.fetch_events(), "snapshot"), store.catalog(),
                       start=None, end=None)["total"]
    override(store)
    current = build_report(store.prepare_events(db.fetch_events(), "current"), store.catalog(),
                           start=None, end=None)["total"]
    assert current["api_usd_known"] > old["api_usd_known"]
    assert current["fast_surcharge_usd"] == pytest.approx(current["standard_api_usd_known"] * 2)
    # Source reparsing replaces events but must not discard their immutable price reference.
    store_events(db, [original])
    reopened = PricingStore(database=Database(db.path))
    frozen = build_report(reopened.prepare_events(db.fetch_events(), "snapshot"), reopened.catalog(),
                          start=None, end=None)["total"]
    assert frozen == old
    assert frozen["inferred_price_calls"] == 1
    reopened.delete_override("gpt-5.6-sol")
    assert build_report(reopened.prepare_events(db.fetch_events(), "snapshot"), reopened.catalog(),
                        start=None, end=None)["total"] == old


def test_delayed_scan_selects_price_revision_at_request_time(tmp_path):
    db = Database(tmp_path / "usage.sqlite3")
    original = PriceCatalog.load_default().payload
    changed = copy.deepcopy(original)
    changed["models"]["gpt-5.6-sol"]["api_usd"]["input"] = 100
    db.record_price_revision(original, "2026-09-20T00:00:00+00:00")
    db.record_price_revision(changed, "2026-09-20T02:00:00+00:00")
    store_events(db, [event("before"), event("after", "2026-09-20T02:01:00+00:00"),
                      event("backfill", "2026-09-19T23:59:59+00:00")])
    db.capture_price_snapshots()
    snapshots, revisions = db.price_snapshot_data(["before", "after", "backfill"])
    assert snapshots["before"]["revision_id"] != snapshots["after"]["revision_id"]
    assert snapshots["before"]["inferred"] == 0
    assert snapshots["after"]["inferred"] == 0
    assert snapshots["backfill"]["inferred"] == 1
    assert snapshots["backfill"]["revision_id"] == snapshots["before"]["revision_id"]
    assert len(revisions) == 2


def test_unknown_model_stays_unknown_in_original_snapshot(tmp_path):
    db = Database(tmp_path / "usage.sqlite3")
    store = PricingStore(database=db)
    store_events(db, [event("unknown", model="not-priced")])
    override(store, "not-priced")
    frozen = build_report(store.prepare_events(db.fetch_events(), "snapshot"), store.catalog(),
                          start=None, end=None)
    current = build_report(store.prepare_events(db.fetch_events(), "current"), store.catalog(),
                           start=None, end=None)
    assert frozen["total"]["unknown_price_calls"] == 1
    assert current["total"]["unknown_price_calls"] == 0


def test_hourly_totals_timezone_and_repeated_dst_hour():
    events = [event("first", "2026-11-01T05:15:00+00:00"),
              event("second", "2026-11-01T06:15:00+00:00")]
    report = build_report(events, PriceCatalog.load_default(), start=None, end=None,
                          timezone="America/New_York")
    assert len(report["hourly"]) == 2
    assert report["hourly"][0]["key"].endswith("-04:00")
    assert report["hourly"][1]["key"].endswith("-05:00")
    assert sum(row["total_tokens"] for row in report["hourly"]) == report["total"]["total_tokens"]
    assert sum(row["api_usd_known"] for row in report["hourly"]) == pytest.approx(report["total"]["api_usd_known"])


def test_sessions_hourly_and_all_exports_share_price_mode_and_range(tmp_path):
    app = create_app(Settings(codex_home=tmp_path, data_dir=tmp_path / "data", scan_interval_minutes=0))
    store_events(app.state.database, [event("one"), event("two", "2026-09-20T02:20:00+00:00", session="two"),
                                      event("three", "2026-09-20T03:00:00+00:00", session="two", model="unknown-model")])
    app.state.database.save_session_titles({"one": "修复 <页面>", "two": "第二个任务"})
    client = TestClient(app)
    params = {"start": "2026-09-20", "end": "2026-09-20", "start_time": "09:00", "end_time": "10:59", "price_mode": "snapshot"}
    frozen = client.get("/api/summary", params=params).json()
    override(app.state.pricing)
    assert client.get("/api/summary", params=params).json()["total"] == frozen["total"]
    default_params = {key: value for key, value in params.items() if key != "price_mode"}
    default_report = client.get("/api/summary", params=default_params).json()
    assert default_report["range"]["price_mode"] == "snapshot"
    assert default_report["total"] == frozen["total"]
    current_report = client.get("/api/summary", params={**params, "price_mode": "current"}).json()
    assert current_report["total"]["api_usd_known"] != frozen["total"]["api_usd_known"]
    sessions = client.get("/api/sessions", params=params).json()["sessions"]
    assert {row["title"] for row in sessions} == {"修复 <页面>", "第二个任务"}
    assert sum(row["api_usd_known"] for row in sessions) == pytest.approx(frozen["total"]["api_usd_known"])
    detail = client.get("/api/sessions/detail", params={**params, "session": "one"}).json()
    assert detail["total"]["calls"] == 1
    assert detail["requests"][0]["price_snapshot"]["inferred"] is True
    assert detail["hourly"][0]["label"] == "09-20 09:00"
    project = client.get("/api/projects/daily", params={**params, "project": "e:/code/test"}).json()
    assert project["total"] == frozen["total"]
    export = client.get("/api/export.csv", params={**default_params, "grain": "hourly"})
    rows = list(csv.DictReader(io.StringIO(export.text.lstrip("\ufeff"))))
    assert len(rows) == 2
    assert all(row["price_mode"] == "snapshot" for row in rows)
    assert sum(float(row["api_usd_known"]) for row in rows) == pytest.approx(frozen["total"]["api_usd_known"])
    assert client.get("/sessions").status_code == 200
    assert client.get("/api/summary", params={"price_mode": "bad"}).status_code == 400


def test_session_request_pagination_and_isolation(tmp_path):
    app = create_app(Settings(codex_home=tmp_path, data_dir=tmp_path / "data", scan_interval_minutes=0))
    events = [event(str(i), f"2026-09-20T01:{i:02d}:00+00:00") for i in range(55)]
    events.append(event("other", session="other", input_tokens=999))
    store_events(app.state.database, events)
    client = TestClient(app)
    first = client.get("/api/sessions/detail", params={"session": "one"}).json()
    next_page = client.get("/api/sessions/detail", params={"session": "one", "offset": 50}).json()
    assert first["request_count"] == 55
    assert first["requests"][0]["key"] == "54"
    assert len(first["requests"]) == 50 and len(next_page["requests"]) == 5
    assert first["total"]["input_tokens"] == 5500
    assert not {row["key"] for row in first["requests"]} & {row["key"] for row in next_page["requests"]}
    assert client.get("/api/sessions/detail", params={"session": "missing"}).status_code == 404
    assert client.get("/api/sessions/detail", params={"session": "one", "offset": -1}).status_code == 400


def test_session_groups_follow_explicit_multilevel_ancestry_without_double_counting():
    catalog = PriceCatalog.load_default()
    events = [
        event("root-call", session="root", service_tier="standard"),
        event("child-call", session="child", is_subagent=1),
        event("grand-call", session="grand", is_subagent=1, model="not-priced",
              service_tier="unknown", project_path="E:/Code/another"),
        event("orphan-call", session="orphan", is_subagent=1, model="not-priced"),
    ]
    metadata = {
        "root": {"parent_session_id": None, "is_subagent": False},
        "middle": {"parent_session_id": "root", "is_subagent": True},
        "child": {"parent_session_id": "middle", "is_subagent": True},
        "grand": {"parent_session_id": "child", "is_subagent": True},
        "orphan": {"parent_session_id": None, "is_subagent": True},
    }
    rows = build_sessions_report(events + [events[1]], catalog, {"root": "父任务"}, metadata)
    assert [row["key"] for row in rows] == ["root", "orphan"]
    root, orphan = rows
    assert root["title"] == "父任务"
    assert root["scope"] == "tree" and root["has_children"] is True
    assert root["is_subagent"] is False and root["parent_unknown"] is False
    assert root["session_ids"] == ["root", "middle", "child", "grand"]
    assert [(row["key"], row["depth"], row["calls"]) for row in root["members"]] == [
        ("root", 0, 1), ("middle", 1, 0), ("child", 2, 1), ("grand", 3, 1),
    ]
    assert all(row["scope"] == "self" for row in root["members"])
    assert root["projects"] == ["another", "test"]
    direct = build_report(events[:3], catalog, start=None, end=None)["total"]
    for field, value in direct.items():
        if field != "key":
            assert root[field] == value
    assert root["standard_calls"] == root["fast_calls"] == root["unknown_tier_calls"] == 1
    assert root["unknown_price_calls"] == 1
    assert sum(row["calls"] for row in rows) == 4
    assert sum(row["calls"] for row in root["members"]) == root["calls"]
    assert orphan["is_subagent"] is True and orphan["parent_unknown"] is True
    assert orphan["has_children"] is False


def test_session_members_keep_each_branch_together_in_depth_first_order():
    parents = {
        "root": None, "branch-a": "root", "branch-z": "root",
        "grand-a": "branch-a", "grand-z": "branch-a", "grand-0": "branch-z",
    }
    metadata = {key: {"parent_session_id": parent, "is_subagent": parent is not None}
                for key, parent in parents.items()}
    events = [event(key, session=key) for key in reversed(parents)]
    root = build_sessions_report(events, PriceCatalog.load_default(), {}, metadata)[0]
    expected = ["root", "branch-a", "grand-a", "grand-z", "branch-z", "grand-0"]
    assert root["session_ids"] == expected
    assert [member["key"] for member in root["members"]] == expected
    assert [member["depth"] for member in root["members"]] == [0, 1, 2, 2, 1, 2]
    assert root["calls"] == sum(member["calls"] for member in root["members"]) == 6


def test_session_cycles_and_unknown_parents_do_not_invent_a_root():
    events = [event(key, session=key, is_subagent=1) for key in ("a", "b", "leaf", "lost")]
    metadata = {
        "a": {"parent_session_id": "b", "is_subagent": True},
        "b": {"parent_session_id": "a", "is_subagent": True},
        "leaf": {"parent_session_id": "a", "is_subagent": True},
    }
    rows = build_sessions_report(events, PriceCatalog.load_default(), {}, metadata)
    assert {row["key"] for row in rows} == {"a", "b", "leaf", "lost"}
    assert sum(row["calls"] for row in rows) == 4
    assert all(row["calls"] == 1 and row["parent_unknown"] for row in rows)
    assert {row["key"] for row in rows if row["lineage_cycle"]} == {"a", "b", "leaf"}
    assert all(not row["has_children"] for row in rows)


def test_session_tree_and_self_details_share_range_prices_and_requests(tmp_path, monkeypatch):
    app = create_app(Settings(codex_home=tmp_path, data_dir=tmp_path / "data", scan_interval_minutes=0))
    metadata = {
        "root": {"parent_session_id": None, "is_subagent": False},
        "middle": {"parent_session_id": "root", "is_subagent": True},
        "child": {"parent_session_id": "middle", "is_subagent": True},
        "grand": {"parent_session_id": "child", "is_subagent": True},
    }
    monkeypatch.setattr(app.state.database, "session_metadata", lambda: metadata, raising=False)
    store_events(app.state.database, [
        event("root-call", "2026-09-20T01:00:00+00:00", session="root", service_tier="standard"),
        event("child-call", "2026-09-20T02:00:00+00:00", session="child", is_subagent=1),
        event("grand-call", "2026-09-20T03:00:00+00:00", session="grand", is_subagent=1,
              model="not-priced", service_tier="unknown"),
        event("other-call", "2026-09-20T02:30:00+00:00", session="other"),
    ])
    app.state.database.save_session_titles({"root": "父任务", "child": "子任务"})
    client = TestClient(app)
    params = {"start": "2026-09-20", "end": "2026-09-20", "start_time": "10:00",
              "end_time": "10:59", "price_mode": "snapshot"}
    sessions = client.get("/api/sessions", params=params).json()["sessions"]
    root = next(row for row in sessions if row["key"] == "root")
    assert root["title"] == "父任务" and root["calls"] == 1
    assert root["session_ids"] == ["root", "middle", "child"]
    assert [member["calls"] for member in root["members"]] == [0, 0, 1]
    tree = client.get("/api/sessions/detail", params={**params, "session": "root", "scope": "tree"}).json()
    child = client.get("/api/sessions/detail", params={**params, "session": "child"}).json()
    own = client.get("/api/sessions/detail", params={**params, "session": "root"}).json()
    assert tree["scope"] == "tree" and child["scope"] == own["scope"] == "self"
    assert tree["total"] == child["total"]
    assert tree["session"]["key"] == "root" and child["session"]["key"] == "child"
    assert tree["request_count"] == 1 and tree["requests"][0]["key"] == "child-call"
    assert own["total"]["calls"] == own["request_count"] == own["session"]["calls"] == 0
    assert own["requests"] == own["daily"] == own["hourly"] == []
    assert client.get("/api/sessions/detail", params={**params, "session": "grand"}).status_code == 404
    assert client.get("/api/sessions/detail", params={**params, "session": "child", "scope": "tree"}).status_code == 404
    assert client.get("/api/sessions/detail", params={**params, "session": "root", "scope": "bad"}).status_code == 400

    full_params = {**params, "start_time": "09:00", "end_time": "11:59"}
    full = client.get("/api/sessions/detail", params={**full_params, "session": "root", "scope": "tree"}).json()
    assert full["request_count"] == full["total"]["calls"] == 3
    assert {row["key"] for row in full["requests"]} == {"root-call", "child-call", "grand-call"}
    assert full["total"]["unknown_price_calls"] == full["total"]["unknown_tier_calls"] == 1
    assert sum(row["calls"] for row in full["hourly"]) == 3
    assert sum(row["api_usd_known"] for row in full["hourly"]) == pytest.approx(full["total"]["api_usd_known"])
    override(app.state.pricing)
    assert client.get("/api/sessions/detail", params={**full_params, "session": "root", "scope": "tree"}).json()["total"] == full["total"]
    current = client.get("/api/sessions/detail", params={**full_params, "session": "root", "scope": "tree", "price_mode": "current"}).json()
    assert current["total"]["api_usd_known"] != full["total"]["api_usd_known"]


@pytest.mark.parametrize("direction", ["ascending", "descending"])
@pytest.mark.parametrize("field", ["input_tokens", "cached_input_tokens", "output_tokens",
                                   "api_usd_known", "fast_surcharge_usd"])
def test_session_request_sorting_precedes_pagination(tmp_path, field, direction):
    app = create_app(Settings(codex_home=tmp_path, data_dir=tmp_path / "data", scan_interval_minutes=0))
    events = [event(str(i), f"2026-09-20T01:{i:02d}:00+00:00",
                    input_tokens=100 + i, cached_input_tokens=i, output_tokens=i)
              for i in range(55)]
    events.append(event("unknown", model="not-priced", input_tokens=10000))
    store_events(app.state.database, events)
    client = TestClient(app)
    params = {"session": "one", "sort_by": field, "sort_direction": direction}
    first = client.get("/api/sessions/detail", params=params).json()
    second = client.get("/api/sessions/detail", params={**params, "offset": 50}).json()
    rows = first["requests"] + second["requests"]
    assert len(rows) == 56 and len({row["key"] for row in rows}) == 56
    if field in {"api_usd_known", "fast_surcharge_usd"}:
        assert rows[-1]["key"] == "unknown"
        rows = rows[:-1]
    values = [row[field] for row in rows]
    assert values == sorted(values, reverse=direction == "descending")
    assert first["total"] == second["total"]
    assert client.get("/api/sessions/detail", params={**params, "sort_by": "bad"}).status_code == 400
    assert client.get("/api/sessions/detail", params={**params, "sort_direction": "bad"}).status_code == 400


@pytest.mark.parametrize("direction,expected", [
    ("ascending", ["known-zero", "standard-estimate", "known-large", "unpriced"]),
    ("descending", ["known-large", "standard-estimate", "known-zero", "unpriced"]),
])
def test_session_request_sorting_includes_standard_estimates(tmp_path, monkeypatch, direction, expected):
    app = create_app(Settings(codex_home=tmp_path, data_dir=tmp_path / "data", scan_interval_minutes=0))
    catalog = PriceCatalog.load_default()
    catalog.models["gpt-5.6-sol"]["api_fast_multiplier"] = None
    monkeypatch.setattr(app.state.pricing, "catalog", lambda: catalog)
    store_events(app.state.database, [
        event("standard-estimate"),
        event("known-zero", model="gpt-6.1-sol", input_tokens=0, cached_input_tokens=0, output_tokens=0),
        event("known-large", model="gpt-6.1-sol", input_tokens=10000, output_tokens=1000),
        event("unpriced", model="not-priced"),
    ])
    client = TestClient(app)

    report = client.get("/api/sessions/detail", params={
        "session": "one", "sort_by": "api_usd_known", "sort_direction": direction,
        "price_mode": "current",
    }).json()

    rows = report["requests"]
    assert [row["key"] for row in rows] == expected
    estimate = next(row for row in rows if row["key"] == "standard-estimate")
    assert estimate["api_standard_fallback"] is True
    assert estimate["api_usd_known"] > 0
    assert estimate["unknown_price_calls"] == estimate["priced_calls"] == 1
    assert rows[-1]["priced_calls"] == 0


def test_titles_use_metadata_and_survive_source_removal(tmp_path: Path):
    db = Database(tmp_path / "usage.sqlite3")
    index = tmp_path / "session_index.jsonl"
    index.write_text(json.dumps({"id": "one", "thread_name": "索引标题"}) + "\ninvalid\n", encoding="utf-8")
    with closing(sqlite3.connect(tmp_path / "state_5.sqlite")) as source:
        source.execute("CREATE TABLE threads(id TEXT, title TEXT, private_message TEXT)")
        source.executemany("INSERT INTO threads VALUES (?, ?, ?)",
                           [("one", "旧标题", "不可读取的消息正文"), ("two", "数据库标题", "另一条正文")])
        source.commit()
    scanner = SessionScanner(codex_home=tmp_path, database=db, timezone="Asia/Taipei")
    scanner.scan()
    assert db.session_titles() == {"one": "索引标题", "two": "数据库标题"}
    index.unlink()
    (tmp_path / "state_5.sqlite").unlink()
    scanner.scan()
    assert db.session_titles()["one"] == "索引标题"
