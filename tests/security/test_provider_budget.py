from frw_api.services.provider_budget import provider_is_available


class _Result:
    def __init__(self, row):
        self.row = row

    def mappings(self):
        return self

    def first(self):
        return self.row


class _Db:
    def __init__(self, row):
        self.row = row

    def execute(self, *_args, **_kwargs):
        return _Result(self.row)


def _row(**overrides):
    row = {
        "routing_mode": "FREE_ONLY",
        "billing_mode": "free_quota",
        "paid_allowed": False,
        "kill_switch_enabled": False,
        "current_period_usage": 0,
        "hard_limit": 10,
    }
    row.update(overrides)
    return row


def test_paid_disabled_provider_is_unavailable():
    assert not provider_is_available(_Db(_row(routing_mode="PAID_DISABLED")), "gemini")


def test_local_only_blocks_nonlocal_provider():
    assert not provider_is_available(_Db(_row(routing_mode="LOCAL_ONLY")), "gemini")


def test_free_only_provider_is_available_under_hard_limit():
    assert provider_is_available(_Db(_row()), "gemini")
