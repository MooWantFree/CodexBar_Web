from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from decimal import Decimal
from importlib.resources import files
from typing import Any

# API dollar multipliers, maintained separately from subscription credit pricing.
# CodexBar-style table, supplemented by Sol's published model-card Fast rates.
# https://developers.openai.com/api/docs/models/gpt-6-sol
# https://developers.openai.com/api/docs/models/gpt-6-luna
# https://developers.openai.com/api/docs/models/gpt-6.1-sol
API_FAST_MULTIPLIERS = {
    "gpt-5.4": 2.0, "gpt-5.4-mini": 2.0, "gpt-5.5": 2.5,
    "gpt-5.6-sol": 2.0, "gpt-5.6-terra": 2.0, "gpt-5.6-luna": 2.0,
    "gpt-6-astra": 2.0, "gpt-6-sol": 2.0, "gpt-6-luna": 2.0, "gpt-6.1-sol": 2.0,
}
FAST_PRICING_VERSION = 4


@dataclass(frozen=True, slots=True)
class PriceResult:
    api_usd: Decimal | None
    codex_credits: Decimal | None
    standard_api_usd: Decimal | None
    standard_codex_credits: Decimal | None
    is_long_context: bool
    model_known: bool
    service_tier: str
    tier_known: bool
    api_tier_multiplier: Decimal | None
    credit_tier_multiplier: Decimal | None


class PriceCatalog:
    def __init__(self, payload: dict[str, Any]) -> None:
        payload = copy.deepcopy(payload)
        # Repair the former implicit 1x default when reading old snapshots. Preserve
        # explicit user overrides and the original Standard rates/date in the snapshot.
        saved_fast_version = payload.get("fast_pricing_version") or 0
        if payload.get("snapshot_source") and saved_fast_version < FAST_PRICING_VERSION:
            overridden = payload.get("snapshot_overrides", [])
            for model, entry in payload["models"].items():
                if model in overridden:
                    continue
                if not saved_fast_version:
                    entry["api_fast_multiplier"] = API_FAST_MULTIPLIERS.get(model)
                elif entry.get("api_fast_multiplier") is None and model in API_FAST_MULTIPLIERS:
                    # Fill previously unknown Fast rates without replacing saved
                    # numeric multipliers, Standard rates, or snapshot dates.
                    entry["api_fast_multiplier"] = API_FAST_MULTIPLIERS[model]
        self.payload = payload
        self.as_of = str(payload["as_of"])
        self.currency = str(payload["currency"])
        self.basis_tokens = Decimal(str(payload["basis_tokens"]))
        self.service_tiers = list(payload.get("service_tiers", ["standard", "priority"]))
        self.sources = list(payload.get("sources", []))
        self.models = dict(payload["models"])
        self.aliases = dict(payload.get("aliases", {}))
        self.context = dict(payload["context"])

    @classmethod
    def load_default(cls) -> PriceCatalog:
        resource = files("codex_token_report").joinpath("data/pricing.json")
        return cls(json.loads(resource.read_text(encoding="utf-8")))

    def display_name(self, model: str | None) -> str:
        if not model:
            return "未知模型"
        entry = self.models.get(self.normalize_model(model))
        return str(entry.get("display_name", model)) if entry else model

    def normalize_model(self, model: str | None) -> str:
        raw = str(model or "").strip().lower()
        raw = raw.removeprefix("openai/")
        raw = str(self.aliases.get(raw, raw))
        if raw not in self.models:
            base = re.sub(r"-\d{4}-\d{2}-\d{2}$", "", raw)
            if base in self.models:
                return base
        return raw

    def is_openai_model(self, model: str | None) -> bool:
        key = self.normalize_model(model)
        entry = self.models.get(key)
        if not entry or "/" in key:
            return False
        # models.dev entries are imported exclusively from its OpenAI provider.
        # Built-in first-party models also have documented Standard prices.
        return entry.get("price_source") == "models_dev" or bool(
            re.match(r"^(?:gpt-|chatgpt-|o[1-9](?:$|-))", key)
        )

    def can_estimate_fast_from_standard(self, model: str | None) -> bool:
        key = self.normalize_model(model)
        entry = self.models.get(key)
        return bool(
            entry and self.is_openai_model(key) and not entry.get("manual_price_override")
            and key not in self.payload.get("snapshot_overrides", [])
        )

    def calculate(
        self,
        *,
        model: str | None,
        input_tokens: int,
        cached_input_tokens: int,
        cache_write_input_tokens: int,
        output_tokens: int,
        service_tier: str | None = "standard",
    ) -> PriceResult:
        normalized_model = self.normalize_model(model)
        entry = self.models.get(normalized_model)
        is_long = input_tokens > int(
            (entry or {}).get("context_threshold", self.context["long_context_threshold"])
        )
        normalized_tier = str(service_tier or "unknown").strip().lower()
        if normalized_tier == "fast":
            normalized_tier = "priority"
        tier_known = normalized_tier in {"standard", "priority"}
        if not tier_known:
            normalized_tier = "unknown"
        if entry is None:
            return PriceResult(
                None,
                None,
                None,
                None,
                is_long,
                False,
                normalized_tier,
                tier_known,
                Decimal(1),
                Decimal(1),
            )

        uncached = max(0, input_tokens - cached_input_tokens - cache_write_input_tokens)
        input_multiplier = Decimal(str(self.context["long_input_multiplier"] if is_long else 1))
        cached_multiplier = Decimal(
            str(self.context["long_cached_input_multiplier"] if is_long else 1)
        )
        write_multiplier = Decimal(
            str(self.context["long_cache_write_multiplier"] if is_long else 1)
        )
        output_multiplier = Decimal(str(self.context["long_output_multiplier"] if is_long else 1))

        api = entry["api_usd"]
        if is_long and entry.get("api_usd_long_context"):
            api = {key: value if value is not None else api.get(key)
                   for key, value in entry["api_usd_long_context"].items()}
            input_multiplier = cached_multiplier = write_multiplier = output_multiplier = Decimal(1)
        cache_write_rate = api.get("cache_write")
        api_price_complete = (
            (cache_write_input_tokens == 0 or cache_write_rate is not None)
            and (cached_input_tokens == 0 or api.get("cached_input") is not None)
        )
        standard_api_usd = (
            Decimal(uncached) * Decimal(str(api["input"])) * input_multiplier
            + Decimal(cached_input_tokens) * Decimal(str(api.get("cached_input") or 0)) * cached_multiplier
            + Decimal(cache_write_input_tokens)
            * Decimal(str(cache_write_rate or 0))
            * write_multiplier
            + Decimal(output_tokens) * Decimal(str(api["output"])) * output_multiplier
        ) / self.basis_tokens
        raw_multiplier = entry.get("api_fast_multiplier")
        api_tier_multiplier = Decimal(1)
        # Keep Standard priced even when a model has no known Fast multiplier.
        if normalized_tier == "priority":
            api_tier_multiplier = Decimal(str(raw_multiplier)) if raw_multiplier is not None else None
        api_usd = (
            standard_api_usd * api_tier_multiplier
            if api_price_complete and api_tier_multiplier is not None else None
        )

        credit = entry.get("codex_credits")
        standard_codex_credits: Decimal | None = None
        if credit and (cache_write_input_tokens == 0 or credit.get("cache_write") is not None):
            credit_write_rate = credit.get("cache_write") or 0
            standard_codex_credits = (
                Decimal(uncached) * Decimal(str(credit["input"]))
                + Decimal(cached_input_tokens) * Decimal(str(credit["cached_input"]))
                + Decimal(cache_write_input_tokens) * Decimal(str(credit_write_rate))
                + Decimal(output_tokens) * Decimal(str(credit["output"]))
            ) / self.basis_tokens
        raw_credit_multiplier = entry.get("credit_fast_multiplier")
        credit_tier_multiplier = Decimal(1)
        if normalized_tier == "priority":
            credit_tier_multiplier = (
                Decimal(str(raw_credit_multiplier)) if raw_credit_multiplier is not None else None
            )
        codex_credits = (
            standard_codex_credits * credit_tier_multiplier
            if standard_codex_credits is not None and credit_tier_multiplier is not None
            else None
        )

        return PriceResult(
            api_usd,
            codex_credits,
            standard_api_usd if api_price_complete else None,
            standard_codex_credits,
            is_long,
            True,
            normalized_tier,
            tier_known,
            api_tier_multiplier,
            credit_tier_multiplier,
        )

    def public_metadata(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of,
            "currency": self.currency,
            "basis_tokens": int(self.basis_tokens),
            "service_tiers": self.service_tiers,
            "sources": self.sources,
            "context": self.context,
            "models": self.models,
        }
