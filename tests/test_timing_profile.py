import pytest

from server.timing_profile import TimingProfile, compute_max_wait, percentile


def test_percentile_interpolates():
    assert percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 90) == pytest.approx(9.1)
    assert percentile([500], 90) == 500


def test_max_wait_rule_and_bounds():
    assert compute_max_wait([]) == 6000
    assert compute_max_wait([420, 1300, 2600, 900, 3100]) == 3900   # p90 = 2900, +1000
    assert compute_max_wait([100, 200, 300]) == 2000                 # floor
    assert compute_max_wait([9000, 9500]) == 6000                    # cap


def test_profile_save_load_and_keep_recent(tmp_path):
    p = TimingProfile(user_id="u/1")
    p.add([0, 1500, 2500] + [1000] * 250)
    assert len(p.inner_pauses_ms) == 200 and 0 not in p.inner_pauses_ms
    p.save(tmp_path)
    q = TimingProfile.load("u/1", tmp_path)
    assert q.inner_pauses_ms == p.inner_pauses_ms and q.max_wait_ms == p.max_wait_ms
    assert (tmp_path / "u_1.json").exists()
    assert set(q.to_json()) == {"user_id", "inner_pauses_ms", "max_wait_ms", "updated"}
