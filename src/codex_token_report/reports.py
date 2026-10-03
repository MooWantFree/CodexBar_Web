from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from .pricing import PriceCatalog, PriceResult


def _empty_bucket(key: str) -> dict[str, Any]:
    return {
        "key": key,
        "calls": 0,
        "input_tokens": 0,
        "uncached_input_tokens": 0,
        "cached_input_tokens": 0,
        "cache_write_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
        "total_tokens": 0,
        "long_context_calls": 0,
        "standard_calls": 0,
        "fast_calls": 0,
        "unknown_tier_calls": 0,
        "fast_tokens": 0,
        "priced_calls": 0,
        "unpriced_tokens": 0,
        "api_usd_known": Decimal(0),
        "standard_api_usd_known": Decimal(0),
        "fast_surcharge_usd": Decimal(0),
        "unknown_fast_price_calls": 0,
        "fast_standard_fallback_calls": 0,
        "fast_standard_fallback_usd": Decimal(0),
        "credits_known": Decimal(0),
        "standard_credits_known": Decimal(0),
        "credit_priced_calls": 0,
        "inferred_price_calls": 0,
    }


def _add_event(
    bucket: dict[str, Any], event: dict[str, Any], catalog: PriceCatalog,
    *, fast_standard_fallback: bool = True, result: PriceResult | None = None,
) -> PriceResult:
    input_tokens = int(event["input_tokens"])
    cached = int(event["cached_input_tokens"])
    cache_write = int(event["cache_write_input_tokens"])
    output = int(event["output_tokens"])
    service_tier = str(event.get("service_tier") or "unknown")
    event_catalog = event.get("_price_catalog", catalog)
    pricing_model = event.get("pricing_model") or event.get("model")
    if result is None:
        result = event_catalog.calculate(
            model=pricing_model,
            input_tokens=input_tokens,
            cached_input_tokens=cached,
            cache_write_input_tokens=cache_write,
            output_tokens=output,
            service_tier=service_tier,
        )
    service_tier = result.service_tier
    bucket["calls"] += 1
    bucket["inferred_price_calls"] += int(event.get("price_snapshot", {}).get("inferred", False))
    bucket["input_tokens"] += input_tokens
    bucket["uncached_input_tokens"] += max(0, input_tokens - cached - cache_write)
    bucket["cached_input_tokens"] += cached
    bucket["cache_write_input_tokens"] += cache_write
    bucket["output_tokens"] += output
    bucket["reasoning_output_tokens"] += int(event["reasoning_output_tokens"])
    bucket["total_tokens"] += input_tokens + output
    bucket["long_context_calls"] += int(result.is_long_context)
    if service_tier == "priority":
        bucket["fast_calls"] += 1
        bucket["fast_tokens"] += input_tokens + output
    elif service_tier == "standard":
        bucket["standard_calls"] += 1
    else:
        bucket["unknown_tier_calls"] += 1
    if result.standard_api_usd is not None:
        bucket["standard_api_usd_known"] += result.standard_api_usd
    if service_tier == "priority" and result.api_usd is None:
        bucket["unknown_fast_price_calls"] += 1
    if result.api_usd is not None:
        bucket["priced_calls"] += 1
        bucket["api_usd_known"] += result.api_usd
        bucket["fast_surcharge_usd"] += result.api_usd - (
            result.standard_api_usd if result.standard_api_usd is not None else result.api_usd
        )
    else:
        bucket["unpriced_tokens"] += input_tokens + output
        if (
            fast_standard_fallback
            and service_tier == "priority"
            and result.api_tier_multiplier is None
            and result.standard_api_usd is not None
            and event_catalog.can_estimate_fast_from_standard(pricing_model)
        ):
            # Count a displayable Standard base without claiming the Fast rate
            # is known, adding a surcharge, or increasing price coverage.
            bucket["priced_calls"] += 1
            bucket["api_usd_known"] += result.standard_api_usd
            bucket["fast_standard_fallback_calls"] += 1
            bucket["fast_standard_fallback_usd"] += result.standard_api_usd
    if result.codex_credits is not None:
        bucket["credit_priced_calls"] += 1
        bucket["credits_known"] += result.codex_credits
        bucket["standard_credits_known"] += result.standard_codex_credits or Decimal(0)
    return result


def _serialize_bucket(bucket: dict[str, Any]) -> dict[str, Any]:
    result = dict(bucket)
    result["api_usd_known"] = float(bucket["api_usd_known"])
    result["standard_api_usd_known"] = float(bucket["standard_api_usd_known"])
    result["fast_surcharge_usd"] = float(bucket["fast_surcharge_usd"])
    result["fast_standard_fallback_usd"] = float(bucket["fast_standard_fallback_usd"])
    result["credits_known"] = float(bucket["credits_known"])
    result["standard_credits_known"] = float(bucket["standard_credits_known"])
    confirmed_priced_calls = bucket["priced_calls"] - bucket["fast_standard_fallback_calls"]
    result["unknown_price_calls"] = bucket["calls"] - confirmed_priced_calls
    result["unknown_credit_calls"] = bucket["calls"] - bucket["credit_priced_calls"]
    result["price_coverage_percent"] = (
        round(confirmed_priced_calls / bucket["calls"] * 100, 2) if bucket["calls"] else 0
    )
    result["tier_coverage_percent"] = (
        round((bucket["calls"] - bucket["unknown_tier_calls"]) / bucket["calls"] * 100, 2)
        if bucket["calls"]
        else 0
    )
    return result


def build_report(
    events: list[dict[str, Any]],
    catalog: PriceCatalog,
    *,
    start: str | None,
    end: str | None,
    timezone: str = "Asia/Taipei",
    fast_standard_fallback: bool = True,
) -> dict[str, Any]:
    total = _empty_bucket("total")
    daily: dict[str, dict[str, Any]] = defaultdict(dict)
    models: dict[str, dict[str, Any]] = defaultdict(dict)
    daily_models: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    hourly: dict[str, dict] = {}
    hourly_models: dict[str, dict] = defaultdict(dict)

    for event in events:
        date_key = str(event["local_date"])
        model_key = str(event.get("model") or "unknown")
        if not daily[date_key]:
            daily[date_key] = _empty_bucket(date_key)
        if not models[model_key]:
            models[model_key] = _empty_bucket(model_key)
            models[model_key]["display_name"] = catalog.display_name(event.get("model"))
        if model_key not in daily_models[date_key]:
            daily_models[date_key][model_key] = _empty_bucket(model_key)
            daily_models[date_key][model_key]["model"] = model_key
            daily_models[date_key][model_key]["display_name"] = catalog.display_name(
                event.get("model")
            )
        # A request has one price; reuse it across every grouping in this report.
        result = _add_event(total, event, catalog, fast_standard_fallback=fast_standard_fallback)
        _add_event(daily[date_key], event, catalog,
                   fast_standard_fallback=fast_standard_fallback, result=result)
        _add_event(models[model_key], event, catalog,
                   fast_standard_fallback=fast_standard_fallback, result=result)
        _add_event(daily_models[date_key][model_key], event, catalog,
                   fast_standard_fallback=fast_standard_fallback, result=result)
        if event.get("timestamp_utc"):
            stamp = datetime.fromisoformat(event["timestamp_utc"]).astimezone(ZoneInfo(timezone))
            # Include UTC offset to keep the two repeated DST hours distinct.
            hour_key = stamp.replace(minute=0, second=0, microsecond=0).isoformat()
            if hour_key not in hourly:
                hourly[hour_key] = _empty_bucket(hour_key)
                hourly[hour_key]["label"] = stamp.strftime("%m-%d %H:00")
            if model_key not in hourly_models[hour_key]:
                hourly_models[hour_key][model_key] = _empty_bucket(model_key)
                hourly_models[hour_key][model_key]["model"] = model_key
                hourly_models[hour_key][model_key]["display_name"] = catalog.display_name(model_key)
            _add_event(hourly[hour_key], event, catalog,
                       fast_standard_fallback=fast_standard_fallback, result=result)
            _add_event(hourly_models[hour_key][model_key], event, catalog,
                       fast_standard_fallback=fast_standard_fallback, result=result)

    daily_rows = []
    for key in sorted(daily):
        row = _serialize_bucket(daily[key])
        model_items = [
            _serialize_bucket(daily_models[key][model_key])
            for model_key in daily_models[key]
        ]
        model_items.sort(key=lambda item: item["total_tokens"], reverse=True)
        row["models"] = model_items
        daily_rows.append(row)
    model_rows = [_serialize_bucket(models[key]) for key in models]
    model_rows.sort(key=lambda item: item["total_tokens"], reverse=True)
    unknown_models = [row["key"] for row in model_rows if row["unknown_price_calls"]]

    return {
        "range": {"start": start, "end": end},
        "total": _serialize_bucket(total),
        "daily": daily_rows,
        "hourly": [
            {**_serialize_bucket(hourly[key]), "models": [
                _serialize_bucket(bucket) for bucket in hourly_models[key].values()
            ]} for key in sorted(hourly, key=lambda value: datetime.fromisoformat(value).timestamp())
        ],
        "models": model_rows,
        "unknown_models": unknown_models,
        "pricing": catalog.public_metadata(),
        "notes": [
            "cached input 已包含在 input tokens 中。",
            "Fast 请求由 logs_2.sqlite 中 response.create/Submission 的 priority 证据按 turn_id 关联。",
            "API 等价金额逐请求应用 Standard/Fast 与长上下文倍率，不是订阅最终账单。",
            "无法确认服务档位的请求按 Standard 基础价估算，并单独显示档位覆盖率。",
            "工具调用、套餐抵扣、合同折扣和区域处理倍率不在金额中。",
        ],
    }


def _project_fields(event: dict[str, Any]) -> tuple[str, str, str | None]:
    path = str(event.get("project_path") or "").strip() or None
    key = str(event.get("project_key") or "").strip() or "unknown"
    display_name = path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1] if path else "未知项目"
    return key, display_name, path


def build_projects_report(
    events: list[dict[str, Any]],
    catalog: PriceCatalog,
    *,
    start: str | None,
    end: str | None,
) -> dict[str, Any]:
    projects: dict[str, dict[str, Any]] = {}
    project_models: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for event in events:
        project_key, display_name, path = _project_fields(event)
        if project_key not in projects:
            projects[project_key] = _empty_bucket(project_key)
            projects[project_key].update({"display_name": display_name, "path": path})
        model_key = str(event.get("model") or "unknown")
        if model_key not in project_models[project_key]:
            project_models[project_key][model_key] = _empty_bucket(model_key)
            project_models[project_key][model_key].update(
                {
                    "model": model_key,
                    "display_name": catalog.display_name(event.get("model")),
                }
            )
        result = _add_event(projects[project_key], event, catalog)
        _add_event(project_models[project_key][model_key], event, catalog, result=result)

    rows: list[dict[str, Any]] = []
    for project_key, bucket in projects.items():
        row = _serialize_bucket(bucket)
        row["models"] = sorted(
            (
                _serialize_bucket(model_bucket)
                for model_bucket in project_models[project_key].values()
            ),
            key=lambda item: item["total_tokens"],
            reverse=True,
        )
        rows.append(row)
    rows.sort(key=lambda item: item["total_tokens"], reverse=True)
    return {"range": {"start": start, "end": end}, "projects": rows}


def build_project_daily_report(
    events: list[dict[str, Any]],
    catalog: PriceCatalog,
    *,
    project_key: str,
    project_path: str | None,
    start: str | None,
    end: str | None,
    timezone: str = "Asia/Taipei",
) -> dict[str, Any]:
    report = build_report(events, catalog, start=start, end=end, timezone=timezone)
    display_name = (
        project_path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
        if project_path
        else "未知项目"
    )
    return {
        "range": report["range"],
        "project": {
            "key": project_key,
            "display_name": display_name,
            "path": project_path,
        },
        "total": report["total"],
        "models": report["models"],
        "daily": report["daily"],
        "hourly": report["hourly"],
        "unknown_models": report["unknown_models"],
    }


def session_key(event: dict) -> str:
    return str(event.get("session_id") or "file:" + str(event.get("source_file") or event["event_id"]))


def _session_bucket(key: str, titles: dict, metadata: dict) -> dict:
    bucket = _empty_bucket(key)
    info = metadata.get(key) or {}
    parent = str(info.get("parent_session_id") or "").strip() or None
    bucket.update({
        "title": titles.get(key) or f"会话 {key[:12]}",
        "title_generated": not bool(titles.get(key)),
        "projects": set(), "models": set(), "project_entries": {}, "model_entries": {},
        "last_activity": "",
        "is_subagent": bool(info.get("is_subagent")), "parent_session_id": parent,
    })
    return bucket


def _add_session_event(
    bucket: dict, event: dict, catalog: PriceCatalog, *, result: PriceResult | None = None,
) -> PriceResult:
    result = _add_event(bucket, event, catalog, result=result)
    project_key, project_name, project_path = _project_fields(event)
    model_key = str(event.get("model") or "unknown")
    model_name = catalog.display_name(event.get("model"))
    bucket["projects"].add(project_name)
    bucket["models"].add(model_name)
    bucket["project_entries"][project_key] = {
        "key": project_key, "display_name": project_name, "path": project_path,
    }
    bucket["model_entries"][model_key] = {"key": model_key, "display_name": model_name}
    bucket["last_activity"] = max(bucket["last_activity"], event["timestamp_utc"])
    return result


def _serialize_session(bucket: dict) -> dict:
    return {
        **_serialize_bucket(bucket), "projects": sorted(bucket["projects"]),
        "models": sorted(bucket["models"]),
        "project_entries": sorted(bucket["project_entries"].values(),
                                  key=lambda entry: (entry["display_name"], entry["key"])),
        "model_entries": sorted(bucket["model_entries"].values(),
                                key=lambda entry: (entry["display_name"], entry["key"])),
    }


def _session_lineage(key: str, metadata: dict) -> tuple[str, list[str], bool]:
    """Return an explicit ancestor chain; cyclic chains have no trustworthy root."""
    path = []
    visited = set()
    current = key
    while current not in visited:
        visited.add(current)
        path.append(current)
        info = metadata.get(current) or {}
        parent = str(info.get("parent_session_id") or "").strip()
        if not parent:
            return current, path, False
        current = parent
    return key, [key], True


def build_sessions_report(
    events: list[dict], catalog: PriceCatalog, titles: dict, metadata: dict | None = None,
) -> list[dict]:
    metadata = metadata or {}
    own = {}
    unique_events = []
    seen = set()
    for event in events:
        event_id = event["event_id"]
        if event_id in seen:
            continue
        seen.add(event_id)
        key = session_key(event)
        if key not in own:
            own[key] = _session_bucket(key, titles, metadata)
        result = _add_session_event(own[key], event, catalog)
        unique_events.append((event, result))
        own[key]["is_subagent"] |= bool(event.get("is_subagent"))

    sessions = {}
    lineages = {}
    for key in own:
        root, path, cycle = _session_lineage(key, metadata)
        lineages[key] = root
        if root not in sessions:
            sessions[root] = _session_bucket(root, titles, metadata)
            sessions[root].update({"member_depths": {}, "lineage_cycle": False})
        group = sessions[root]
        group["lineage_cycle"] |= cycle
        for index, member in enumerate(path):
            depth = len(path) - index - 1
            group["member_depths"][member] = depth
    for event, result in unique_events:
        _add_session_event(sessions[lineages[session_key(event)]], event, catalog, result=result)

    rows = []
    for root, group in sessions.items():
        members = []
        children = defaultdict(list)
        for key in group["member_depths"]:
            if key != root:
                parent = str((metadata.get(key) or {}).get("parent_session_id") or "").strip()
                children[parent].append(key)
        ordered = []
        stack = [root]
        while stack:
            key = stack.pop()
            ordered.append(key)
            stack.extend(sorted(children[key], reverse=True))
        for key in ordered:
            member = _serialize_session(own.get(key) or _session_bucket(key, titles, metadata))
            member.update({
                "depth": group["member_depths"][key], "scope": "self",
                "lineage_cycle": group["lineage_cycle"],
                "parent_unknown": group["lineage_cycle"] or bool(
                    member["is_subagent"] and not member["parent_session_id"]
                ),
            })
            members.append(member)
        row = _serialize_session(group)
        row.pop("member_depths")
        root_member = next(member for member in members if member["key"] == root)
        row.update({
            "is_subagent": root_member["is_subagent"],
            "parent_unknown": root_member["parent_unknown"], "scope": "tree",
            "session_ids": ordered, "has_children": len(members) > 1, "members": members,
        })
        rows.append(row)
    # Completely unpriced sessions follow all sessions with known costs, including zero.
    rows.sort(key=lambda row: (row["priced_calls"] > 0, row["api_usd_known"],
                              row["total_tokens"], row["last_activity"], row["key"]), reverse=True)
    return rows


def request_rows(events: list[dict], catalog: PriceCatalog) -> list[dict]:
    rows = []
    for event in reversed(events):
        bucket = _empty_bucket(event["event_id"])
        _add_event(bucket, event, catalog)
        serialized = _serialize_bucket(bucket)
        rows.append({**serialized, "timestamp": event["timestamp_utc"],
                     "api_standard_fallback": bool(bucket["fast_standard_fallback_calls"]),
                     "api_cost_unknown": bool(serialized["unknown_price_calls"]),
                     "model": catalog.display_name(event.get("model")),
                     "model_id": str(event.get("model") or "unknown"),
                     "service_tier": event.get("service_tier") or "unknown",
                     "price_snapshot": event.get("price_snapshot")})
    return rows
