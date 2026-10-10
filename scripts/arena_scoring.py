"""Serializable arena score snapshots and usage pricing."""

import math


DEFAULTS = {"profile": "efficiency", "win": 3, "loss": -3, "failure": -5,
            "tie": 0, "bye": 3, "speed_weight": 1, "expense_weight": 1}


def _number(value, name, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number; unknown metrics cannot be scored")
    if value < 0 or (positive and value == 0):
        raise ValueError(f"{name} must be {'positive' if positive else 'nonnegative'}")
    return value


def calculate_cost(usage, prices):
    """Price inclusive counters without counting cached/reasoning tokens twice.

    Rates are USD per million tokens: input, cached_input, output. Missing
    counters or needed prices return None; known invalid counters raise ValueError.
    Reasoning output is already part of output_tokens and is never added again.
    """
    values = [usage.get(k) for k in ("input_tokens", "cached_input_tokens", "output_tokens")]
    if any(v is None for v in values):
        return None
    total, cached, output = [_number(v, k) for v, k in zip(values, ("input_tokens", "cached_input_tokens", "output_tokens"))]
    if cached > total:
        raise ValueError("cached_input_tokens cannot exceed inclusive input_tokens")
    reasoning = usage.get("reasoning_output_tokens")
    if reasoning is not None and _number(reasoning, "reasoning_output_tokens") > output:
        raise ValueError("reasoning_output_tokens cannot exceed inclusive output_tokens")
    categories = ((total - cached, "input"), (cached, "cached_input"), (output, "output"))
    cost = 0
    for count, category in categories:
        rate = prices.get(category, prices.get(category + "_per_1m", prices.get(category + "_per_million")))
        if count and rate is None:
            return None
        if rate is not None:
            cost += count * _number(rate, category + " price") / 1_000_000
    return cost


def _summary(row, original):
    metrics = row.get("metrics", [])
    if not isinstance(metrics, list):
        raise ValueError("row metrics must be a list of attempt/episode metrics")
    for metric in metrics:
        if not isinstance(metric, dict) or type(metric.get("complete")) is not bool:
            raise ValueError("each metric must be an object with a boolean complete flag")
        for key in ("elapsed_ms", "cost_usd", "input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens"):
            if metric.get(key) is not None:
                _number(metric[key], key)
    complete = [m for m in metrics if m.get("complete") is True]
    summary = {"completions": len(complete), "attempts": len(metrics),
               "latency_per_completion": None, "amortized_latency": None,
               "cost_per_completion": None, "throughput": None,
               "price_per_1m": None, "cost_index": None}
    if not complete:
        if original:
            raise ValueError("original profile requires a complete cohort with measured throughput for every competitor")
        return summary
    elapsed = sum(_number(m.get("elapsed_ms"), "elapsed_ms", positive=True) for m in complete)
    all_cost = sum(_number(m.get("cost_usd"), "cost_usd") for m in metrics)
    summary["latency_per_completion"] = elapsed / len(complete)
    summary["cost_per_completion"] = all_cost / len(complete)
    if all(m.get("elapsed_ms") is not None for m in metrics):
        summary["amortized_latency"] = sum(_number(m["elapsed_ms"], "elapsed_ms") for m in metrics) / len(complete)
    if original:
        successful_tokens = sum(_number(m.get("input_tokens"), "input_tokens") +
                                _number(m.get("output_tokens"), "output_tokens") for m in complete)
        all_tokens = sum(_number(m.get("input_tokens"), "input_tokens") +
                         _number(m.get("output_tokens"), "output_tokens") for m in metrics)
        if not successful_tokens or not all_tokens:
            raise ValueError("original profile requires positive measured tokens for the complete cohort")
        summary["throughput"] = successful_tokens / elapsed * 1000
        summary["price_per_1m"] = all_cost / all_tokens * 1_000_000
        summary["cost_index"] = summary["throughput"] * summary["price_per_1m"]
    return summary


def _normalize(value, lower, upper, offset, scale):
    return 0 if upper == lower else offset + scale * (value - lower) / (upper - lower)


def _calibration(settings):
    calibration = settings.get("original")
    if not isinstance(calibration, dict):
        raise ValueError("original calibration is required")
    products = []
    for key, model, effort in (("min", "gpt-5.6-luna", "low"), ("max", "gpt-6-astra", "ultra")):
        item = calibration.get(key, {})
        if item.get("model") != model or item.get("effort") != effort:
            raise ValueError(f"original calibration {key} must identify {model}/{effort}")
        products.append(_number(item.get("throughput"), "calibration throughput", positive=True) *
                        _number(item.get("price_per_1m"), "calibration price_per_1m"))
    if products[1] < products[0]:
        raise ValueError("original calibration maximum cost index is below minimum")
    return products


def score_snapshot(rows, config):
    """Return a new cohort snapshot. Does not mutate rows or previous snapshots.

    Each row has id, wins/losses/failures/ties/byes, cumulative stage metrics,
    and optionally prior efficiency_points. contribution is the new round's
    efficiency award; efficiency_points includes the prior accumulated awards.
    """
    settings = {**DEFAULTS, **config.get("scoring", {})}
    for key in ("win", "loss", "failure", "tie", "bye", "speed_weight", "expense_weight"):
        value = settings[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"scoring {key} must be finite numeric data")
        if key in ("speed_weight", "expense_weight") and value < 0:
            raise ValueError(f"scoring {key} must be nonnegative")
    profile = settings["profile"]
    if profile not in ("efficiency", "original"):
        raise ValueError("scoring profile must be efficiency or original")
    original = profile == "original"
    bounds = _calibration(settings) if original else None
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("snapshot rows must be objects")
    for row in rows:
        for key in ("wins", "losses", "failures", "ties", "byes"):
            if type(row.get(key, 0)) is not int or row.get(key, 0) < 0:
                raise ValueError(f"{key} must be a nonnegative integer")
        prior = row.get("efficiency_points", 0)
        if isinstance(prior, bool) or not isinstance(prior, (int, float)) or not math.isfinite(prior):
            raise ValueError("efficiency_points must be finite numeric data")
    identifiers = [row.get("id") for row in rows]
    if len(set(identifiers)) != len(identifiers) or any(not isinstance(i, str) or not i for i in identifiers):
        raise ValueError("snapshot rows require unique nonempty ids")
    summaries = [_summary(row, original) for row in rows]
    valid = [s for s in summaries if s["completions"]]
    speed_values = [s["throughput"] if original else s["latency_per_completion"] for s in valid]
    cost_values = [s["cost_per_completion"] for s in valid]
    speed_bounds = [min(speed_values), max(speed_values)] if speed_values else [0, 0]
    cost_bounds = bounds if original else ([min(cost_values), max(cost_values)] if cost_values else [0, 0])
    entries = []
    for row, summary in zip(rows, summaries):
        speed = cost = 0
        if summary["completions"]:
            speed = _normalize(summary["throughput"] if original else summary["latency_per_completion"],
                               *speed_bounds, -1 if original else 1, 2 if original else -2)
            cost = _normalize(summary["cost_index"] if original else summary["cost_per_completion"], *cost_bounds, 2, -4)
        contribution = speed * settings["speed_weight"] + cost * settings["expense_weight"]
        base = sum(row.get(k, 0) * settings[v] for k, v in
                   (("wins", "win"), ("losses", "loss"), ("failures", "failure"), ("ties", "tie"), ("byes", "bye")))
        accumulated = row.get("efficiency_points", 0) + contribution
        entries.append({"id": row["id"], **summary, "speed_score": speed, "cost_score": cost,
                        "contribution": contribution, "base_points": base,
                        "efficiency_points": accumulated, "points": base + accumulated})
    return {"profile": profile, "speed_bounds": speed_bounds, "cost_bounds": cost_bounds, "entries": entries}
