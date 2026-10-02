from __future__ import annotations

import copy
import json
import re
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import quote

import httpx

from .db import Database
from .models_dev import CATALOG_CACHE_KEY, CATALOG_URL, fetch_catalog, parse_model, valid_models
from .pricing import API_FAST_MULTIPLIERS, FAST_PRICING_VERSION, PriceCatalog

_DOCS_HOST = "developers.openai.com"
_MODEL_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    return format(normalized, "f")


class PricingStore:
    def __init__(
        self,
        *,
        database: Database,
        fetch_models: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self.database = database
        self._fetch_models_override = fetch_models
        self._lock = threading.RLock()
        self._refresh_lock = threading.Lock()
        bundled = PriceCatalog.load_default().payload
        self.database.initialize_pricing_catalog(
            payload_json=json.dumps(bundled, ensure_ascii=False),
            source="bundled",
            fetched_at=str(bundled.get("as_of") or "") or None,
        )
        self.capture()

    def capture(self) -> None:
        with self._lock:
            payload = self.catalog().payload
            payload["snapshot_source"] = self.database.get_pricing_catalog()["source"]
            payload["snapshot_overrides"] = sorted(self.database.get_pricing_overrides())
            self.database.record_price_revision(payload, datetime.now(UTC).isoformat())
            self.database.capture_price_snapshots()

    def prepare_events(self, events: list[dict], mode: str) -> list[dict]:
        with self._lock:
            self.capture()
            snapshots, revisions = self.database.price_snapshot_data(
                [event["event_id"] for event in events]
            )
            catalogs = {
                key: PriceCatalog(json.loads(row["payload_json"]))
                for key, row in revisions.items()
            }
            for event in events:
                event.pop("_price_catalog", None)
                snapshot = snapshots.get(event["event_id"])
                if snapshot:
                    revision = revisions[snapshot["revision_id"]]
                    saved_catalog = catalogs[snapshot["revision_id"]]
                    model = saved_catalog.normalize_model(event.get("pricing_model") or event.get("model"))
                    event["price_snapshot"] = {
                        "revision_id": snapshot["revision_id"],
                        "observed_at": revision["observed_at"],
                        "captured_at": snapshot["captured_at"],
                        "inferred": bool(snapshot["inferred"]),
                        "price_date": catalogs[snapshot["revision_id"]].as_of,
                        "source": "override" if model in saved_catalog.payload.get("snapshot_overrides", [])
                        else saved_catalog.payload.get("snapshot_source", "unknown"),
                    }
                    if mode == "snapshot":
                        event["_price_catalog"] = catalogs[snapshot["revision_id"]]
            return events

    def _base_payload(self) -> dict[str, Any]:
        row = self.database.get_pricing_catalog()
        saved = json.loads(str(row["payload_json"]))
        payload = PriceCatalog.load_default().payload
        # Legacy document prices are no longer a fallback source. Keep previous
        # models.dev entries until the complete catalog has been acquired.
        for model, entry in saved["models"].items():
            if entry.get("price_source") == "models_dev":
                payload["models"][model] = entry
                payload["as_of"] = saved["as_of"]
        cache = self._cached_models()
        if cache:
            models = set(payload["models"]) | {
                self._canonical_model(model) for model in self.database.distinct_models()
            }
            for model in models:
                try:
                    parsed = parse_model(model, cache["catalog"])
                except (TypeError, ValueError):
                    continue
                self._apply_model(payload, model, parsed, cache["fetched_at"])
            payload["as_of"] = cache["fetched_at"][:10]
        for model, entry in payload["models"].items():
            entry["api_fast_multiplier"] = API_FAST_MULTIPLIERS.get(model)
        return payload

    @staticmethod
    def _canonical_model(model: str) -> str:
        raw = model.strip().lower()
        raw = raw.removeprefix("openai/")
        return PriceCatalog.load_default().normalize_model(raw)

    def _cached_models(self) -> dict[str, Any] | None:
        cached = self.database.get_metadata(CATALOG_CACHE_KEY)
        if cached is None:
            return None
        return json.loads(cached)

    @staticmethod
    def _apply_model(payload: dict, model: str, parsed: dict, fetched_at: str) -> None:
        entry = payload["models"].setdefault(
            model, {"codex_credits": None, "credit_fast_multiplier": None},
        )
        # CodexBar supplements missing cache rates with bundled prices, never
        # a previous model card's rates or a different provider's same-name row.
        bundled = PriceCatalog.load_default().models.get(model, {})
        for field in ("cached_input", "cache_write"):
            if parsed["api_usd"][field] is None:
                parsed["api_usd"][field] = bundled.get("api_usd", {}).get(field)
        entry.update(parsed)
        entry.update(api_fast_multiplier=API_FAST_MULTIPLIERS.get(model),
                     source_url=CATALOG_URL, price_source="models_dev", fetched_at=fetched_at)

    def catalog(self) -> PriceCatalog:
        with self._lock:
            payload = copy.deepcopy(self._base_payload())
            payload["fast_pricing_version"] = FAST_PRICING_VERSION
            overrides = self.database.get_pricing_overrides()
            for model, override in overrides.items():
                entry = payload["models"].setdefault(
                    model,
                    {
                        "display_name": model,
                        "codex_credits": None,
                        "credit_fast_multiplier": 1.0,
                    },
                )
                entry["api_usd"] = {
                    "input": float(override["input_usd"]),
                    "cached_input": float(override["cached_input_usd"]),
                    "cache_write": (
                        float(override["cache_write_usd"])
                        if override["cache_write_usd"] is not None
                        else None
                    ),
                    "output": float(override["output_usd"]),
                }
                multiplier = override["api_fast_multiplier"]
                entry["api_fast_multiplier"] = float(multiplier) if multiplier != "unknown" else None
                entry.pop("api_usd_long_context", None)
            return PriceCatalog(payload)

    @staticmethod
    def _rates(entry: dict[str, Any] | None) -> dict[str, Any] | None:
        if not entry or not entry.get("api_usd"):
            return None
        api = entry["api_usd"]
        return {
            "input": api.get("input"),
            "cached_input": api.get("cached_input"),
            "cache_write": api.get("cache_write"),
            "output": api.get("output"),
            "api_fast_multiplier": entry.get("api_fast_multiplier"),
        }

    def public_state(self) -> dict[str, Any]:
        with self._lock:
            row = self.database.get_pricing_catalog()
            base = self._base_payload()
            overrides = self.database.get_pricing_overrides()
            effective = self.catalog().payload
            discovered = {
                self._canonical_model(model)
                for model in self.database.distinct_models()
                if model.strip()
            }
            models = sorted(set(base["models"]) | set(overrides) | discovered)
            items = []
            for model in models:
                base_entry = base["models"].get(model)
                effective_entry = effective["models"].get(model)
                override = overrides.get(model)
                items.append(
                    {
                        "model": model,
                        "display_name": (
                            effective_entry or base_entry or {}
                        ).get("display_name", model),
                        "official": self._rates(base_entry),
                        "override": (
                            {
                                "input": override["input_usd"],
                                "cached_input": override["cached_input_usd"],
                                "cache_write": override["cache_write_usd"],
                                "output": override["output_usd"],
                                "api_fast_multiplier": (override["api_fast_multiplier"] if override["api_fast_multiplier"] != "unknown" else None),
                            }
                            if override
                            else None
                        ),
                        "effective": self._rates(effective_entry),
                        "source": (base_entry or {}).get("price_source", row["source"]),
                        "source_url": (
                            base_entry or {}
                        ).get(
                            "source_url",
                            f"https://{_DOCS_HOST}/api/docs/models/{quote(model, safe='')}",
                        ),
                        "fetched_at": (base_entry or {}).get("fetched_at"),
                        "override_updated_at": override["updated_at"] if override else None,
                    }
                )
            return {
                "as_of": base.get("as_of"),
                "currency": base.get("currency", "USD"),
                "basis_tokens": base.get("basis_tokens", 1_000_000),
                "source": row["source"],
                "fetched_at": row["fetched_at"],
                "refresh_attempted_at": row["refresh_attempted_at"],
                "refresh_error": row["refresh_error"],
                "models": items,
            }

    def set_override(self, model: str, values: dict[str, Decimal | None]) -> None:
        with self._lock:
            self.capture()
            self._set_override(model, values)
            self.capture()

    def _set_override(self, model: str, values: dict[str, Decimal | None]) -> None:
        normalized = model.strip().lower()
        if not _MODEL_PATTERN.fullmatch(normalized):
            raise ValueError("模型 ID 只能包含小写字母、数字、点、下划线和连字符")
        now = datetime.now(UTC).isoformat()
        self.database.set_pricing_override(
            model=normalized,
            values={
                "input_usd": _decimal_text(values["input"]),
                "cached_input_usd": _decimal_text(values["cached_input"]),
                "cache_write_usd": (
                    _decimal_text(values["cache_write"])
                    if values["cache_write"] is not None
                    else None
                ),
                "output_usd": _decimal_text(values["output"]),
                "api_fast_multiplier": (_decimal_text(values["api_fast_multiplier"]) if values["api_fast_multiplier"] is not None else "unknown"),
                "updated_at": now,
            },
        )

    def delete_override(self, model: str) -> bool:
        with self._lock:
            self.capture()
            deleted = self.database.delete_pricing_override(model.strip().lower())
            self.capture()
            return deleted

    def _fetch_models(self) -> dict[str, Any]:
        if self._fetch_models_override is not None:
            return self._fetch_models_override()
        return fetch_catalog()

    def refresh_on_startup(
        self, timezone: str, *, now: datetime | None = None,
    ) -> dict[str, Any] | None:
        instant = now or datetime.now(UTC)
        cache = self._cached_models()
        if cache:
            elapsed = instant - datetime.fromisoformat(cache["fetched_at"])
            missing = False
            for model in self.database.distinct_models():
                try:
                    parse_model(self._canonical_model(model), cache["catalog"])
                except (TypeError, ValueError):
                    missing = True
                    break
            if timedelta(0) <= elapsed < timedelta(hours=24) and not missing:
                return None
        if not self.database.claim_pricing_refresh(instant):
            return None
        return self.refresh(now=instant)

    def refresh(self, *, now: datetime | None = None) -> dict[str, Any]:
        with self._refresh_lock:
            with self._lock:
                self.capture()
                row = self.database.get_pricing_catalog()
            payload = self._base_payload()
            models = set(payload["models"])
            for model in self.database.distinct_models():
                models.add(self._canonical_model(model))

            now = now or datetime.now(UTC)
            self.database.set_metadata("models_dev_last_attempt", now.isoformat())
            updated: list[str] = []
            failed: dict[str, str] = {}
            unavailable: list[str] = []
            try:
                remote = self._fetch_models()
                downloaded = valid_models(remote)
                cached = self._cached_models()
                merged = cached["catalog"]["openai"]["models"].copy() if cached else {}
                merged.update(downloaded)
                remote = {"openai": {"models": merged}}
                self.database.set_metadata(CATALOG_CACHE_KEY, json.dumps({
                    "fetched_at": now.isoformat(), "catalog": remote,
                }, ensure_ascii=False))
            except (httpx.HTTPError, UnicodeError, ValueError, TypeError) as exc:
                remote = None
                failed["models.dev"] = str(exc)
            for model in sorted(models):
                if remote is None or not _MODEL_PATTERN.fullmatch(model):
                    continue
                if model not in remote["openai"]["models"]:
                    unavailable.append(model)
                    continue
                try:
                    parsed = parse_model(model, remote)
                    self._apply_model(payload, model, parsed, now.isoformat())
                    updated.append(model)
                except (TypeError, ValueError) as exc:
                    failed[model] = str(exc)

            fetched_at = now.isoformat() if updated else row["fetched_at"]
            if updated:
                payload["as_of"] = now.date().isoformat()
            error = "; ".join(f"{model}: {message}" for model, message in failed.items()) or None
            with self._lock:
                self.capture()
                self.database.save_pricing_catalog(
                    payload_json=json.dumps(payload, ensure_ascii=False),
                    source="models_dev" if updated else str(row["source"]),
                    fetched_at=fetched_at,
                    refresh_attempted_at=now.isoformat(),
                    refresh_error=error,
                )
                self.capture()
            return {
                "updated_models": updated,
                "failed_models": failed,
                "unavailable_models": unavailable,
                "fetched_at": fetched_at,
            }
