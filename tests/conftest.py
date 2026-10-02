import pytest

from codex_token_report import quota
from codex_token_report.pricing_store import PricingStore


@pytest.fixture(autouse=True)
def isolate_pricing_network(monkeypatch):
    original = PricingStore._fetch_models

    def mocked_fetch(self):
        if self._fetch_models_override is None:
            raise ValueError("Pricing network is disabled in tests")
        return original(self)

    monkeypatch.setattr(PricingStore, "_fetch_models", mocked_fetch)


@pytest.fixture(autouse=True)
def isolate_quota_rpc(monkeypatch):
    command = quota._codex_command
    enter = quota.CodexRPC.__enter__

    def mocked_enter(self):
        # Explicit fake CLI tests replace the command; ordinary lifespan tests
        # must never launch a real client or query the developer's account.
        if quota._codex_command is command:
            raise quota.QuotaError("Quota RPC is disabled in tests")
        return enter(self)

    monkeypatch.setattr(quota.CodexRPC, "__enter__", mocked_enter)
