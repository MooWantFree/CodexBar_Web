import pytest

from codex_token_report.pricing_store import PricingStore


@pytest.fixture(autouse=True)
def isolate_pricing_network(monkeypatch):
    original = PricingStore._fetch_models

    def mocked_fetch(self):
        if self._fetch_models_override is None:
            raise ValueError("Pricing network is disabled in tests")
        return original(self)

    monkeypatch.setattr(PricingStore, "_fetch_models", mocked_fetch)
