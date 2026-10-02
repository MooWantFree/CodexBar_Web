"""Relate a live quota window to the API value of locally recorded requests."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from .db import Database
from .pricing_store import PricingStore
from .quota_history import BOUNDARY_TOLERANCE
from .reports import build_report


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _utc_time(value: Any) -> datetime | None:
    try:
        if isinstance(value, str):
            result = datetime.fromisoformat(value)
            return result.astimezone(UTC) if result.tzinfo is not None else None
        seconds = _number(value)
        return datetime.fromtimestamp(seconds, UTC) if seconds is not None else None
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _recorded_start(
    window: dict, inferred: datetime, records: list[dict], fetched: datetime,
) -> tuple[datetime | None, bool]:
    candidates = []
    for record in records:
        if not isinstance(record, dict) or (
            record.get("limit_id") != window.get("limit_id")
            or _number(record.get("window_minutes")) != window["window_minutes"]
        ):
            continue
        start = _utc_time(record.get("reset_at"))
        if start is None or not 0 <= start.timestamp() <= fetched.timestamp():
            continue
        distance = abs((start - inferred).total_seconds())
        if distance > BOUNDARY_TOLERANCE:
            continue
        confirmed = record.get("confidence") == "confirmed" or record.get("method") in {
            "scheduled", "early",
        }
        estimated = record.get("time_estimated")
        if not isinstance(estimated, bool):
            estimated = not confirmed or record.get("method") == "early"
        candidates.append((not confirmed, distance, -start.timestamp(), start, estimated))
    if not candidates:
        return None, False
    selected = min(candidates, key=lambda item: item[:3])
    return selected[3], selected[4]


def build_quota_value_report(
    quota: dict,
    database: Database,
    pricing: PricingStore,
    *,
    price_mode: str = "snapshot",
    timezone: str = "Asia/Taipei",
) -> dict:
    """Value each current Codex window independently, up to its quota snapshot.

    The logs do not identify their account or quota bucket. Only the general
    Codex bucket is matched to local usage, and overlapping windows are not summed.
    """
    if price_mode not in {"snapshot", "current"}:
        raise ValueError("price_mode must be snapshot or current")
    report = {
        "status": quota.get("status", "unavailable"),
        "message": quota.get("message"),
        "plan_type": quota.get("plan_type"),
        "fetched_at": quota.get("fetched_at"),
        "price_mode": price_mode,
        "windows": [],
    }
    if report["status"] != "ready":
        return report
    fetched = _utc_time(quota.get("fetched_at"))
    records = quota.get("reset_records")
    records = records if isinstance(records, list) else []
    windows = quota.get("windows")
    windows = windows if isinstance(windows, list) else []
    eligible: list[tuple[dict, datetime]] = []

    for source in windows:
        if not isinstance(source, dict):
            continue
        used = _number(source.get("used_percent"))
        duration = _number(source.get("window_minutes"))
        reset = _utc_time(source.get("resets_at"))
        row = {
            "limit_id": source.get("limit_id"),
            "limit_name": source.get("limit_name"),
            "slot": source.get("slot"),
            "window_minutes": duration,
            "used_percent": used,
            "remaining_percent": 100 - used if used is not None and 0 <= used <= 100 else None,
            "cycle_start_at": None,
            "cycle_start_estimated": False,
            "resets_at": reset.isoformat() if reset else None,
            "status": "unavailable",
            "message": None,
            "total": None,
            "usd_per_percent": None,
            "full_quota_usd": None,
            "remaining_quota_usd": None,
        }
        report["windows"].append(row)
        if used is None or not 0 <= used <= 100:
            row["message"] = "缺少有效的已消耗百分比，无法计算金额。"
            continue
        if fetched is None or reset is None or duration is None or duration <= 0:
            row["message"] = "缺少有效的额度快照、重置时间或窗口长度，无法确定统计范围。"
            continue
        if reset <= fetched:
            row.update(status="expired", message="快照中的重置时间已过期，请刷新额度后计算。")
            continue
        try:
            inferred = reset - timedelta(minutes=duration)
        except OverflowError:
            row["message"] = "窗口长度超出支持范围，无法确定周期开始时间。"
            continue
        start, estimated = _recorded_start(row, inferred, records, fetched)
        if start is None and used > 0 and 0 <= inferred.timestamp() <= fetched.timestamp():
            start, estimated = inferred, True
        if start is not None:
            row.update(cycle_start_at=start.isoformat(), cycle_start_estimated=estimated)
        if row["limit_id"] != "codex":
            row.update(status="unsupported", message="本地调用日志没有额度组标识，无法分配到此额度组。")
            continue
        if used == 0 and start is None:
            row.update(status="no_usage", message="已消耗为 0%，不推测未使用的滚动窗口或额度美元价值。")
            continue
        if start is None:
            row["message"] = "无法确定当前周期起点，暂不计算金额。"
            continue
        eligible.append((row, start))

    if fetched is None:
        report.update(status="unavailable", message="缺少有效的额度快照时间，请刷新额度后计算。")
        return report
    report["fetched_at"] = fetched.isoformat()
    if not report["windows"]:
        report.update(status="unavailable", message="当前账号未返回可计算的额度窗口。")
        return report
    report["message"] = (
        "API 等价金额按本机日志估算；日志缺少账号标识，无法核对当前账号归属。"
        "不同窗口的统计范围可能重叠，金额请勿相加。"
    )
    if not eligible:
        return report

    # Widen the SQL bounds to whole seconds, then compare parsed timestamps.
    # ISO strings with different fractional precision do not sort numerically.
    first_start = min(start for _, start in eligible).replace(microsecond=0)
    try:
        end_bound = fetched.replace(microsecond=0) + timedelta(seconds=1)
    except OverflowError:
        end_bound = fetched
    events = database.fetch_events(start_at=first_start.isoformat(), end_before=end_bound.isoformat())
    events = pricing.prepare_events(events, price_mode)
    stamped = [(event, _utc_time(event.get("timestamp_utc"))) for event in events]
    catalog = pricing.catalog()
    for row, start in eligible:
        selected = [event for event, stamp in stamped if stamp is not None and start <= stamp < fetched]
        if not selected and row["used_percent"] > 0:
            row.update(status="missing_usage", message="此周期没有本地调用记录，已消耗额度的金额未知。")
            continue
        total = build_report(
            selected, catalog, start=None, end=None, timezone=timezone,
            fast_standard_fallback=False,
        )["total"]
        row["total"] = total
        if row["used_percent"] == 0:
            row.update(status="no_usage", message="已消耗为 0%，无法据此外推每 1% 或整窗价值。")
        else:
            partial = total["unknown_price_calls"] > 0
            row.update(
                status="partial_pricing" if partial else "ready",
                message="按已知金额换算；未定价调用未计入金额。" if partial else None,
            )
            if not total["priced_calls"]:
                row["message"] = "此周期没有已定价调用，暂时无法换算额度美元。"
                continue
            per_percent = Decimal(str(total["api_usd_known"])) / Decimal(str(row["used_percent"]))
            row.update(
                usd_per_percent=float(per_percent),
                full_quota_usd=float(per_percent * 100),
                remaining_quota_usd=float(per_percent * Decimal(str(row["remaining_percent"]))),
            )
    return report
