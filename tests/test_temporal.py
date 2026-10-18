from backend.graph.temporal import is_current


def test_half_open_validity_interval():
    claim = {"valid_from": "2020-01-01T00:00:00Z", "valid_to": "2021-01-01T00:00:00Z"}
    assert not is_current(claim, "2019-12-31T23:59:59Z")
    assert is_current(claim, "2020-01-01T00:00:00Z")
    assert not is_current(claim, "2021-01-01T00:00:00Z")


def test_open_ended_claim():
    assert is_current({"valid_from": "2020-01-01T00:00:00Z"}, "2026-10-04T00:00:00Z")


def test_cutoff_requires_valid_timestamp_and_timezone():
    import pytest
    from backend.tools.common import cutoff
    for value in ("abc", "2026-10-04", "2026-10-04T00:00:00"):
        with pytest.raises(ValueError, match="valid ISO timestamp with a timezone"):
            cutoff(value)
    assert cutoff("2026-10-04T05:30:00+05:30") == "2026-10-04T00:00:00Z"
