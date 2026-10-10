import copy
import pytest

from scripts import arena_scoring as scoring


def row(identifier, latency, cost, complete=True, **counts):
    return {"id": identifier, "metrics": [{"elapsed_ms": latency, "cost_usd": cost,
            "complete": complete, "input_tokens": 100, "output_tokens": 100}], **counts}


def test_efficiency_rewards_low_latency_and_all_attempt_cost_per_completion():
    rows = [row("fast", 10, 1, wins=1), row("slow", 20, 2, losses=1)]
    rows[1]["metrics"].append({"complete": False, "elapsed_ms": 10, "cost_usd": 1})
    before = copy.deepcopy(rows)
    snap = scoring.score_snapshot(rows, {})
    by_id = {x["id"]: x for x in snap["entries"]}
    assert by_id["fast"]["speed_score"] == 1
    assert by_id["slow"]["speed_score"] == -1
    assert by_id["fast"]["cost_score"] == 2
    assert by_id["slow"]["cost_score"] == -2
    assert by_id["slow"]["cost_per_completion"] == 3
    assert by_id["slow"]["latency_per_completion"] == 20
    assert by_id["slow"]["amortized_latency"] == 30
    assert by_id["fast"]["points"] == 6
    assert rows == before


def test_zero_span_and_no_completions_have_neutral_efficiency():
    snap = scoring.score_snapshot([row("a", 10, 1), row("b", 10, 1), row("f", None, None, False, failures=1)], {})
    assert [x["efficiency_points"] for x in snap["entries"]] == [0, 0, 0]
    assert snap["entries"][2]["points"] == -5


def test_complete_missing_metrics_is_rejected():
    with pytest.raises(ValueError, match="cost_usd"):
        scoring.score_snapshot([row("a", 1, None)], {})


def test_cost_does_not_double_count_cached_or_reasoning_tokens():
    assert scoring.calculate_cost({"input_tokens": 1000, "cached_input_tokens": 200,
                                   "output_tokens": 300, "reasoning_output_tokens": 100},
                                  {"input": 2, "cached_input": 1, "output": 10}) == pytest.approx(.0048)
    assert scoring.calculate_cost({"input_tokens": None, "output_tokens": 1}, {"input": 2, "output": 10}) is None
    with pytest.raises(ValueError):
        scoring.calculate_cost({"input_tokens": 1, "cached_input_tokens": 2, "output_tokens": 1}, {"input": 1, "output": 1})


def original():
    return {"scoring": {"profile": "original", "original": {
        "min": {"model": "gpt-5.6-luna", "effort": "low", "throughput": 1, "price_per_1m": 1},
        "max": {"model": "gpt-6-astra", "effort": "ultra", "throughput": 100, "price_per_1m": 10}}}}


def test_original_exact_formula_and_missing_calibration_or_cohort():
    cfg = original()
    rows = [row("a", 1000, .0002), row("b", 2000, .0004)]
    snap = scoring.score_snapshot(rows, cfg)
    a, b = snap["entries"]
    assert a["throughput"] == 200
    assert a["speed_score"] == 1
    assert b["speed_score"] == -1
    assert a["cost_score"] == pytest.approx(2 - 4 * (200 - 1) / 999)
    with pytest.raises(ValueError, match="calibration"):
        scoring.score_snapshot(rows, {"scoring": {"profile": "original"}})
    with pytest.raises(ValueError, match="cohort"):
        scoring.score_snapshot(rows + [row("f", None, None, False)], cfg)
    rows[0]["metrics"][0]["cost_usd"] = None
    with pytest.raises(ValueError, match="cost_usd"):
        scoring.score_snapshot(rows, cfg)


@pytest.mark.parametrize("rows,cfg", [
    ([row("a", 10, 1, wins=-1)], {}),
    ([row("a", 10, 1, wins="one")], {}),
    ([row("a", 10, 1)], {"scoring": {"win": "three"}}),
    ([row("a", 10, 1)], {"scoring": {"speed_weight": float("nan")}}),
    ([{"id": "a", "metrics": [42]}], {}),
])
def test_invalid_numeric_and_metric_boundaries_raise_value_error(rows, cfg):
    with pytest.raises(ValueError):
        scoring.score_snapshot(rows, cfg)
