from impact import config as C
from impact.normalize import attribute


def test_bot_detection():
    assert C.is_bot("stamphog", "User")
    assert C.is_bot("alice", "Bot")
    assert C.is_bot("renovate[bot]", "User")
    assert not C.is_bot("alice", "User")


def test_ai_attribution():
    assert attribute("alice", False, "") == (False, "alice")
    assert attribute("posthog", True, "Requested by @bob in Slack") == (True, "bob")
    assert attribute("posthog", True, "no requester") == (True, None)
    assert attribute("renovate", True, "") == (False, None)


def test_window_bounds():
    assert not (C.WINDOW_START <= "2026-08-04T23:59:59Z")
    assert C.WINDOW_START <= "2026-08-05T00:00:01Z" <= C.WINDOW_END


def test_points_and_weights():
    assert C.pr_points(0) == 1 and abs(C.pr_points(1.5) - 4) < 1e-9 and abs(C.pr_points(3) - 16) < 1e-9
    from impact import paths
    assert paths.weight("pnpm-lock.yaml") == 0
    assert paths.noise("posthog/migrations/0001_x.py") == ("migration", 0.3)
    assert paths.weight("posthog/hogql/parser.py") == 1.5
    assert paths.noise("frontend/src/Button.stories.tsx")[1] == 0.5


def test_contract_validation():
    import pytest
    from impact.contracts import validate
    validate("triage", {"number": 1, "tier": "major", "work_type": "feature", "summary": "x"})
    with pytest.raises(ValueError):
        validate("triage", {"number": 1, "tier": "huge", "work_type": "feature", "summary": "x"})
    with pytest.raises(ValueError):
        validate("recall", {"login": "a", "metrics": {}})
