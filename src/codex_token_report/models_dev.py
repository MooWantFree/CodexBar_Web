from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

CATALOG_URL = "https://models.dev/api.json"
MAX_CATALOG_BYTES = 16_000_000
CATALOG_CACHE_KEY = "models_dev_catalog_v1"


def valid_models(catalog: dict[str, Any]) -> dict[str, Any]:
    """Keep the complete OpenAI catalog, including models not yet used locally."""
    provider = catalog.get("openai")
    models = provider.get("models") if isinstance(provider, dict) else None
    if not isinstance(models, dict):
        raise TypeError("价格目录缺少 OpenAI 模型表")
    valid = {}
    for model in models:
        try:
            parse_model(model, catalog)
        except (TypeError, ValueError):
            continue
        valid[model] = models[model]
    if not valid:
        raise ValueError("价格目录没有有效的 OpenAI 单价，保留上次有效缓存")
    return valid


def fetch_catalog() -> dict[str, Any]:
    with httpx.Client(timeout=20.0, follow_redirects=True) as client, client.stream(
        "GET", CATALOG_URL, headers={"User-Agent": "codex-token-report"},
    ) as response:
        response.raise_for_status()
        if response.url.scheme != "https" or response.url.host != "models.dev":
            raise ValueError("价格目录被重定向到非允许域名")
        body = bytearray()
        for chunk in response.iter_bytes():
            body.extend(chunk)
            if len(body) > MAX_CATALOG_BYTES:
                raise ValueError("价格目录过大")
    payload = json.loads(body)
    provider = payload.get("openai") if isinstance(payload, dict) else None
    if not isinstance(provider, dict) or not isinstance(provider.get("models"), dict):
        raise TypeError("价格目录缺少 OpenAI 模型表")
    return payload


def _rate(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError("价格必须是有限的非负数")
    try:
        price = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("价格不是有效数字") from exc
    if not price.is_finite() or price < 0:
        raise ValueError("价格必须是有限的非负数")
    return float(price)


def _rates(cost: dict[str, Any]) -> dict[str, float | None]:
    return {
        "input": _rate(cost.get("input")), "output": _rate(cost.get("output")),
        "cached_input": _rate(cost.get("cache_read")),
        "cache_write": _rate(cost.get("cache_write")),
    }


def parse_model(model: str, catalog: dict[str, Any]) -> dict[str, Any]:
    # Do not borrow a similarly named model's price from another provider.
    provider = catalog.get("openai")
    models = provider.get("models") if isinstance(provider, dict) else None
    row = models.get(model) if isinstance(models, dict) else None
    if not isinstance(row, dict):
        raise ValueError("models.dev 未提供该 OpenAI 模型")  # noqa: TRY004
    cost = row.get("cost")
    if not isinstance(cost, dict):
        raise ValueError("模型缺少价格")  # noqa: TRY004
    rates = _rates(cost)
    if rates["input"] is None or rates["output"] is None:
        raise ValueError("模型缺少 input/output 价格")
    result: dict[str, Any] = {"api_usd": rates, "display_name": row.get("name") or model}
    # Prefer the explicit context tier and its threshold over the legacy 200k key.
    for tier in cost.get("tiers", []):
        rule = tier.get("tier", {})
        if rule.get("type") == "context" and isinstance(rule.get("size"), int):
            if rule["size"] <= 0:
                raise ValueError("长上下文阈值无效")
            result.update(context_threshold=rule["size"], api_usd_long_context=_rates(tier))
            break
    else:
        long_cost = cost.get("context_over_200k")
        if isinstance(long_cost, dict):
            result.update(context_threshold=200_000, api_usd_long_context=_rates(long_cost))
    return result
