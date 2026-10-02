from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import re
import sqlite3
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, field_validator

from .config import Settings
from .db import Database
from .pricing_store import PricingStore
from .quota import QuotaService
from .quota_value import build_quota_value_report
from .quota_value_history import QuotaValueHistory
from .reports import (
    build_project_daily_report,
    build_projects_report,
    build_report,
    build_sessions_report,
    request_rows,
    session_key,
)
from .scanner import SessionScanner
from .session_quota import SessionQuotaHistory


def _validate_date(value: str | None, field: str) -> str | None:
    if value is None or value == "":
        return None
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{field} 必须是 YYYY-MM-DD") from exc
    return value


@dataclass(frozen=True)
class ReportRange:
    start: str | None
    end: str | None
    start_time: str
    end_time: str
    start_at: str | None
    end_before: str | None
    start_exact: str | None = None
    end_exact: str | None = None
    price_mode: str = "snapshot"

    def public(self) -> dict:
        result = {
            "start": self.start, "end": self.end,
            "start_time": self.start_time, "end_time": self.end_time,
            "price_mode": self.price_mode,
        }
        if self.start_exact and self.end_exact:
            result.update({
                "start_at": self.start_exact, "end_at": self.end_exact, "end_exclusive": True,
            })
        return result


def _report_range(
    start: str | None, end: str | None, start_time: str, end_time: str, timezone: str,
    *, start_exact: str | None = None, end_exact: str | None = None,
) -> ReportRange:
    start = _validate_date(start, "start")
    end = _validate_date(end, "end")
    zone = ZoneInfo(timezone)
    bounds = []
    for day, clock, field in ((start, start_time, "start_time"), (end, end_time, "end_time")):
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", clock):
            raise HTTPException(status_code=400, detail=f"{field} 必须是 HH:MM（00:00–23:59）")
        if not day:
            bounds.append(None)
            continue
        local = datetime.combine(date.fromisoformat(day), time.fromisoformat(clock))
        utc = local.replace(tzinfo=zone).astimezone(UTC)
        if utc.astimezone(zone).replace(tzinfo=None) != local:
            raise HTTPException(status_code=400, detail="所选时间在当前时区不存在")
        bounds.append(utc)
    start_at, end_at = bounds
    if start_exact or end_exact:
        if not start_exact or not end_exact or not start or not end:
            raise HTTPException(status_code=400, detail="精确范围需要两个重置时刻及对应日期")
        exact_bounds = []
        for value, day, clock in ((start_exact, start, start_time), (end_exact, end, end_time)):
            try:
                parsed = datetime.fromisoformat(value)
                if parsed.tzinfo is None:
                    raise ValueError("missing timezone")
                local = parsed.astimezone(zone)
                if local.date().isoformat() != day or local.strftime("%H:%M") != clock:
                    raise ValueError("inconsistent range")
                exact_bounds.append(parsed.astimezone(UTC))
            except (ValueError, OverflowError) as exc:
                raise HTTPException(status_code=400, detail="重置时刻必须含时区且与日期时分一致") from exc
        start_at, end_at = exact_bounds
        if start_at >= end_at:
            raise HTTPException(status_code=400, detail="两个重置时刻必须不同，开始时间须早于结束时间")
    if start_at and end_at and start_at > end_at:
        raise HTTPException(status_code=400, detail="开始时间不能晚于结束时间")
    # End is inclusive through the selected minute, including fractional seconds.
    try:
        end_before = (
            end_at.isoformat() if end_exact else (end_at + timedelta(minutes=1)).isoformat()
        ) if end_at else None
    except OverflowError as exc:
        raise HTTPException(status_code=400, detail="结束时间超出支持范围") from exc
    return ReportRange(
        start, end, start_time, end_time, start_at.isoformat() if start_at else None, end_before,
        start_at.isoformat() if start_exact else None, end_at.isoformat() if end_exact else None,
    )


class PriceOverrideRequest(BaseModel):
    input: Decimal
    cached_input: Decimal
    cache_write: Decimal | None
    output: Decimal
    api_fast_multiplier: Decimal | None = None

    @field_validator("input", "cached_input", "cache_write", "output", "api_fast_multiplier")
    @classmethod
    def validate_price(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and (not value.is_finite() or value < 0):
            raise ValueError("价格和倍率必须是有限的非负数")
        return value


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or Settings.from_env()
    database = Database(active_settings.database_path)
    pricing = PricingStore(database=database)
    value_history = QuotaValueHistory(database, pricing, active_settings.timezone)
    quota = QuotaService(
        active_settings.codex_home, database=database, timezone=active_settings.timezone,
        value_history=value_history,
    )
    scanner = SessionScanner(
        codex_home=active_settings.codex_home,
        database=database,
        timezone=active_settings.timezone,
    )
    session_quotas = SessionQuotaHistory(database)
    package_dir = Path(__file__).resolve().parent
    templates = Jinja2Templates(directory=package_dir / "templates")

    scan_lock = asyncio.Lock()

    async def run_scan(application: FastAPI, *, raise_errors: bool = False):
        async with scan_lock:
            application.state.scan_status = {
                "state": "running",
                "started_at": datetime.now(UTC).isoformat(),
                "finished_at": None,
                "error": None,
            }
            try:
                result = await asyncio.to_thread(scanner.scan)
            except Exception as exc:
                application.state.scan_status = {
                    **application.state.scan_status,
                    "state": "error",
                    "finished_at": datetime.now(UTC).isoformat(),
                    "error": str(exc),
                }
                if raise_errors:
                    raise
                return None
            application.state.scan_status = {
                **application.state.scan_status,
                "state": "complete",
                "finished_at": datetime.now(UTC).isoformat(),
                "error": None,
            }
            return result

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.scan_status = {
            "state": "queued",
            "started_at": None,
            "finished_at": None,
            "error": None,
        }
        initial_task = asyncio.create_task(run_scan(application))
        application.state.pricing_refresh_status = {
            "state": "queued", "started_at": None, "finished_at": None, "error": None,
        }

        async def refresh_startup_pricing() -> None:
            await initial_task
            application.state.pricing_refresh_status.update(
                state="running", started_at=datetime.now(UTC).isoformat(),
            )
            try:
                result = await asyncio.to_thread(pricing.refresh_on_startup, active_settings.timezone)
                if result is None:
                    state, error = "skipped", None
                else:
                    error = "; ".join(
                        f"{model}: {message}" for model, message in result["failed_models"].items()
                    ) or None
                    state = "partial" if error and result["updated_models"] else "error" if error else "complete"
                application.state.pricing_refresh_status.update(state=state, error=error)
            except Exception as exc:
                application.state.pricing_refresh_status.update(state="error", error=str(exc))
                logging.getLogger(__name__).exception("Startup pricing refresh failed")
            finally:
                application.state.pricing_refresh_status["finished_at"] = datetime.now(UTC).isoformat()

        pricing_task = asyncio.create_task(refresh_startup_pricing())
        periodic_task: asyncio.Task | None = None

        async def periodic_scan() -> None:
            while True:
                await asyncio.sleep(active_settings.scan_interval_minutes * 60)
                await run_scan(application)
                await refresh_startup_pricing()

        if active_settings.scan_interval_minutes > 0:
            periodic_task = asyncio.create_task(periodic_scan())
        try:
            yield
        finally:
            tasks = [initial_task, pricing_task]
            if periodic_task:
                tasks.append(periodic_task)
            for task in tasks:
                task.cancel()
            with suppress(asyncio.CancelledError):
                await asyncio.gather(*tasks)

    app = FastAPI(title="Codex Token Report", version="0.5.0", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=package_dir / "static"), name="static")
    app.state.settings = active_settings
    app.state.database = database
    app.state.pricing = pricing
    app.state.scanner = scanner
    app.state.quota = quota
    app.state.session_quotas = session_quotas

    def report_range(
        start: str | None = Query(default=None), end: str | None = Query(default=None),
        start_time: str = Query(default="00:00"), end_time: str = Query(default="23:59"),
        start_at: str | None = Query(default=None), end_at: str | None = Query(default=None),
        price_mode: Literal["current", "snapshot"] = Query(default="snapshot"),
    ) -> ReportRange:
        selected = _report_range(
            start, end, start_time, end_time, active_settings.timezone,
            start_exact=start_at, end_exact=end_at,
        )
        return replace(selected, price_mode=price_mode)

    async def range_events(selected: ReportRange, project_key: str | None = None) -> list[dict]:
        events = await asyncio.to_thread(
            database.fetch_events, selected.start, selected.end, project_key,
            start_at=selected.start_at, end_before=selected.end_before,
        )
        return await asyncio.to_thread(pricing.prepare_events, events, selected.price_mode)

    range_dependency = Depends(report_range)

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(_: Request, _exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": "请求参数无效"})

    @app.get("/", response_class=HTMLResponse)
    @app.get("/overview", response_class=HTMLResponse)
    @app.get("/pricing", response_class=HTMLResponse)
    @app.get("/daily", response_class=HTMLResponse)
    @app.get("/projects", response_class=HTMLResponse)
    @app.get("/resets", response_class=HTMLResponse)
    @app.get("/quota-value", response_class=HTMLResponse)
    @app.get("/sessions", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        end = datetime.now(ZoneInfo(active_settings.timezone)).date()
        start = end
        bounds = database.date_bounds()
        pricing_state = pricing.public_state()
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "default_start": start.isoformat(),
                "default_end": end.isoformat(),
                "minimum_date": bounds[0] or start.isoformat(),
                "maximum_date": bounds[1] or end.isoformat(),
                "codex_home": str(active_settings.codex_home),
                "timezone": active_settings.timezone,
                "pricing_as_of": pricing_state["as_of"],
                "styles_version": (package_dir / "static" / "styles.css").stat().st_mtime_ns,
                "app_version": (package_dir / "static" / "app.js").stat().st_mtime_ns,
            },
        )

    @app.get("/api/summary")
    async def summary(selected: ReportRange = range_dependency) -> dict:
        events = await range_events(selected)
        catalog = pricing.catalog()
        report = build_report(events, catalog, start=selected.start, end=selected.end,
                              timezone=active_settings.timezone)
        report["range"].update(selected.public())
        report["storage"] = database.storage_stats()
        last_scan = database.get_metadata("last_scan")
        report["last_scan"] = json.loads(last_scan) if last_scan else None
        return report

    @app.get("/api/sessions")
    async def sessions(selected: ReportRange = range_dependency) -> dict:
        events = await range_events(selected)
        rows = build_sessions_report(events, pricing.catalog(), database.session_titles(),
                                     database.session_metadata())
        return {"range": selected.public(), "sessions": rows,
                "inferred_price_calls": sum(row["inferred_price_calls"] for row in rows)}

    @app.get("/api/sessions/detail")
    async def session_detail(
        session: str = Query(min_length=1), offset: int = Query(default=0, ge=0),
        limit: int = Query(default=50, ge=1, le=200), selected: ReportRange = range_dependency,
        sort_by: Literal["timestamp", "service_tier", "input_tokens", "cached_input_tokens",
                         "output_tokens", "api_usd_known", "fast_surcharge_usd",
                         "price_snapshot"] = Query(default="timestamp"),
        sort_direction: Literal["ascending", "descending"] = Query(default="descending"),
        scope: Literal["tree", "self"] = Query(default="self"),
    ) -> dict:
        all_events = await range_events(selected)
        catalog = pricing.catalog()
        groups = build_sessions_report(all_events, catalog, database.session_titles(),
                                       database.session_metadata())
        if scope == "tree":
            session_row = next((row for row in groups if row["key"] == session), None)
            session_ids = set(session_row["session_ids"]) if session_row else set()
        else:
            session_row = next((member for row in groups for member in row["members"]
                                if member["key"] == session), None)
            session_ids = {session}
        if session_row is None:
            raise HTTPException(status_code=404, detail="所选范围内没有该会话的调用")
        events = list({event["event_id"]: event for event in all_events
                       if session_key(event) in session_ids}.values())
        report = build_report(events, catalog, start=selected.start, end=selected.end,
                              timezone=active_settings.timezone)
        report["range"].update(selected.public())
        report["scope"] = scope
        report["session"] = session_row
        rows = request_rows(events, catalog)

        def sort_value(row: dict):
            if sort_by == "timestamp":
                return datetime.fromisoformat(row["timestamp"])
            if sort_by == "service_tier":
                return {"priority": "Fast", "standard": "Standard"}.get(row[sort_by], "未知")
            if sort_by == "price_snapshot":
                snapshot = row[sort_by]
                return ("首次采集回填" if snapshot["inferred"] else "当时已保存价格") if snapshot else "无快照"
            if sort_by == "api_usd_known" and row["unknown_price_calls"]:
                return None
            if sort_by == "fast_surcharge_usd" and row["unknown_fast_price_calls"]:
                return None
            return row[sort_by]

        known, unknown = [], []
        for row in rows:
            value = sort_value(row)
            if value is None:
                unknown.append(row)
            else:
                known.append((value, row))
        known.sort(key=lambda item: item[0], reverse=sort_direction == "descending")
        ordered = [row for _, row in known] + unknown
        report["requests"] = ordered[offset:offset + limit]
        report["request_count"] = len(events)
        report["offset"] = offset
        return report

    @app.get("/api/sessions/{key}/quota")
    async def session_quota_records(
        key: str, offset: int = Query(default=0, ge=0),
        limit: int = Query(default=50, ge=1, le=200), include_children: bool = False,
    ) -> dict:
        identities = {key}
        if include_children:
            metadata = await asyncio.to_thread(database.session_metadata)
            pending = [key]
            while pending:
                parent = pending.pop()
                children = {child for child, info in metadata.items()
                            if info.get("parent_session_id") == parent} - identities
                identities.update(children)
                pending.extend(children)
        return await asyncio.to_thread(
            session_quotas.records, session_ids=identities, offset=offset, limit=limit,
        )

    @app.post("/api/scan")
    async def scan() -> dict:
        result = await run_scan(app, raise_errors=True)
        return result.to_dict()

    @app.get("/api/projects")
    async def projects(selected: ReportRange = range_dependency) -> dict:
        events = await range_events(selected)
        report = build_projects_report(
            events, pricing.catalog(), start=selected.start, end=selected.end,
        )
        report["range"].update(selected.public())
        return report

    @app.get("/api/projects/daily")
    async def project_daily(
        project: str = Query(min_length=1),
        selected: ReportRange = range_dependency,
    ) -> dict:
        identity = await asyncio.to_thread(database.project_identity, project)
        if identity is None:
            raise HTTPException(status_code=404, detail="项目不存在")
        events = await range_events(selected, project)
        report = build_project_daily_report(
            events,
            pricing.catalog(),
            project_key=project,
            project_path=identity.get("project_path"),
            start=selected.start,
            end=selected.end,
            timezone=active_settings.timezone,
        )
        report["range"].update(selected.public())
        return report

    @app.get("/api/pricing")
    async def get_pricing() -> dict:
        return await asyncio.to_thread(pricing.public_state)

    @app.get("/api/quota")
    async def get_quota() -> dict:
        return await asyncio.to_thread(quota.read)

    @app.post("/api/quota/refresh")
    async def refresh_quota() -> dict:
        return await asyncio.to_thread(quota.read, force=True)

    @app.get("/api/quota/value")
    async def quota_value(
        price_mode: Literal["current", "snapshot"] = Query(default="snapshot"),
    ) -> dict:
        # Reuse the last explicit read so navigating never fetches live quotas.
        snapshot = quota.cached or QuotaService._empty("unavailable", "请先读取账号额度。")
        report = await asyncio.to_thread(quota.saved_value, price_mode=price_mode)
        if report is None:
            report = await asyncio.to_thread(
                build_quota_value_report, snapshot, database, pricing,
                price_mode=price_mode, timezone=active_settings.timezone,
            )
            report.update({name: snapshot.get(name) for name in (
                "history_mode", "history_label", "history_fetched_at",
            )})
        last_scan = database.get_metadata("last_scan")
        report["last_scan"] = json.loads(last_scan) if last_scan else None
        return report

    @app.get("/api/quota/value/history")
    async def quota_value_history(
        price_mode: Literal["current", "snapshot"] = Query(default="snapshot"),
        offset: int = Query(default=0, ge=0), limit: int = Query(default=20, ge=1, le=100),
    ) -> dict:
        try:
            return await asyncio.to_thread(
                quota.value_records, price_mode=price_mode, offset=offset, limit=limit,
            )
        except (sqlite3.Error, OSError, ValueError, TypeError) as exc:
            raise HTTPException(status_code=503, detail="额度历史读取失败，请稍后重试。") from exc

    @app.get("/api/quota/value/history/{cycle_id}")
    async def quota_value_observations(
        cycle_id: int, price_mode: Literal["current", "snapshot"] = Query(default="snapshot"),
    ) -> dict:
        try:
            result = await asyncio.to_thread(
                quota.value_observations, cycle_id, price_mode=price_mode,
            )
        except (sqlite3.Error, OSError, ValueError, TypeError) as exc:
            raise HTTPException(status_code=503, detail="额度读数历史读取失败，请稍后重试。") from exc
        if result is None:
            raise HTTPException(status_code=404, detail="当前账号没有此周期的历史记录。")
        return result

    @app.post("/api/pricing/refresh")
    async def refresh_pricing() -> dict:
        return await asyncio.to_thread(pricing.refresh)

    @app.put("/api/pricing/models/{model}/override")
    async def set_price_override(model: str, payload: PriceOverrideRequest) -> dict:
        try:
            await asyncio.to_thread(
                pricing.set_override,
                model,
                {
                    "input": payload.input,
                    "cached_input": payload.cached_input,
                    "cache_write": payload.cache_write,
                    "output": payload.output,
                    "api_fast_multiplier": payload.api_fast_multiplier,
                },
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"model": model.strip().lower(), "updated": True}

    @app.delete("/api/pricing/models/{model}/override")
    async def delete_price_override(model: str) -> dict:
        deleted = await asyncio.to_thread(pricing.delete_override, model)
        return {"model": model.strip().lower(), "deleted": deleted}

    @app.get("/api/export.csv")
    async def export_csv(
        selected: ReportRange = range_dependency,
        grain: Literal["daily", "hourly"] = Query(default="daily"),
    ) -> Response:
        events = await range_events(selected)
        catalog = pricing.catalog()
        report = build_report(events, catalog, start=selected.start, end=selected.end,
                              timezone=active_settings.timezone)
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(
            buffer,
            fieldnames=[
                "date",
                "calls",
                "standard_calls",
                "fast_calls",
                "unknown_tier_calls",
                "input_tokens",
                "uncached_input_tokens",
                "cached_input_tokens",
                "cache_write_input_tokens",
                "output_tokens",
                "reasoning_output_tokens",
                "total_tokens",
                "api_usd_known",
                "standard_api_usd_known",
                "fast_surcharge_usd",
                "unknown_fast_price_calls",
                "credits_known",
                "tier_coverage_percent",
                "unknown_price_calls",
                "inferred_price_calls",
                "price_mode",
            ],
        )
        writer.writeheader()
        for row in report[grain]:
            writer.writerow(
                {
                    "date": row["key"],
                    **{field: row[field] for field in writer.fieldnames
                       if field not in {"date", "price_mode"}},
                    "price_mode": selected.price_mode,
                }
            )
        filename = (
            f"codex-token-report-{selected.start or 'all'}-{selected.start_time.replace(':', '')}"
            f"-{selected.end or 'all'}-{selected.end_time.replace(':', '')}"
            f"-{selected.price_mode}-{grain}.csv"
        )
        return Response(
            content="\ufeff" + buffer.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/api/health")
    async def health() -> dict:
        return {
            "status": "ok",
            "scan": app.state.scan_status,
            "pricing_refresh": app.state.pricing_refresh_status,
            "codex_home_exists": active_settings.codex_home.exists(),
            "database": str(active_settings.database_path),
        }

    return app
