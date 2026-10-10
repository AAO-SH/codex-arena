"""Resumable tournament scheduling."""

from copy import deepcopy
from functools import lru_cache
import hashlib
import json
import random

from scripts.arena_scoring import DEFAULTS as SCORE_DEFAULTS, score_snapshot


DEFAULTS = {"entrants": 100, "cut": 20, "tiers": ["iron", "copper", "silver", "gold"],
            "swiss_rounds": 5, "swiss_strikes": 4, "qualifiers": 8,
            "series_games": 10, "extra_games": 5}
COUNTS = {"W": "wins", "L": "losses", "F": "failures", "T": "ties"}


def _settings(config):
    settings = deepcopy(DEFAULTS)
    settings.update(config.get("tournament", {}))
    for name in ("entrants", "cut", "swiss_rounds", "extra_games"):
        if type(settings[name]) is not int or settings[name] < 0:
            raise ValueError(f"tournament {name} must be a nonnegative integer")
    for name in ("swiss_strikes", "qualifiers", "series_games"):
        if type(settings[name]) is not int or settings[name] < 1:
            raise ValueError(f"tournament {name} must be a positive integer")
    tiers = settings["tiers"]
    if not isinstance(tiers, list) or not tiers or any(not isinstance(t, str) or not t for t in tiers) or len(set(tiers)) != len(tiers):
        raise ValueError("tournament tiers must be unique nonempty strings")
    return settings


def _fingerprint(config):
    value = {"seed": config.get("seed", 7), "tournament": _settings(config),
             "scoring": {**SCORE_DEFAULTS, **config.get("scoring", {})}}
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _check(state, config):
    if state.get("schema_version") != 1 or state.get("config_fingerprint") != _fingerprint(config):
        raise ValueError("tournament configuration differs from persisted state")


def _new_stats(ids):
    return {i: {"id": i, "wins": 0, "losses": 0, "failures": 0, "ties": 0,
                "byes": 0, "points": 0, "efficiency_points": 0, "metrics": [], "opponents": []} for i in ids}


def _tie(state, identifier):
    return hashlib.sha256(f"{state['seed']}:{identifier}".encode()).hexdigest()


def _strength(state, identifier):
    return sum(state["stats"][o]["points"] for o in state["stats"][identifier]["opponents"])


def _rank(state, ids):
    return sorted(ids, key=lambda i: (-state["stats"][i]["points"], state["stats"][i]["failures"],
                                     -state["stats"][i]["wins"], -_strength(state, i), _tie(state, i)))


def create_tournament(config, competitors):
    """Create JSON-serializable state. No task execution or inference occurs."""
    settings = _settings(config)
    # Fail invalid profiles/calibration before the caller dispatches any work.
    score_snapshot([], config)
    ids = [c.get("id") for c in competitors]
    if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise ValueError("competitors require unique nonempty string ids")
    if len(ids) != settings["entrants"]:
        raise ValueError("competitor count must equal tournament entrants")
    if settings["cut"] > len(ids):
        raise ValueError("cut cannot exceed competitor count")
    circle = sorted(ids)
    random.Random(config.get("seed", 7)).shuffle(circle)
    if len(circle) % 2:
        circle.append(None)
    rounds = []
    if len(ids) >= 2:
        for _ in range(len(circle) - 1):
            rounds.append([[circle[i], circle[-1-i]] for i in range(len(circle)//2)])
            circle = [circle[0], circle[-1], *circle[1:-1]]
    return {"schema_version": 1, "config_fingerprint": _fingerprint(config),
            "seed": config.get("seed", 7), "competitors": deepcopy(competitors), "ids": ids,
            "status": "running", "stage": "round_robin", "round": 0, "stats": _new_stats(ids),
            "rr_schedule": rounds, "barrier": None, "records": {}, "jobs": {}, "snapshots": [],
            "administrative": [], "stage_results": {}, "removed": [], "tiers": {}, "qualifiers": {},
            "de": {}, "series": {}, "champions": {}, "next_job": 1}


def _job(state, a, b, stage, tier, round_number, game=1, series=None, bracket=None):
    identifier = f"match-{state['next_job']:06d}"
    state["next_job"] += 1
    job = {"id": identifier, "a": a, "b": b, "stage": stage, "tier": tier,
           "round": round_number, "game": game, "series": series}
    if bracket is not None:
        job["bracket"] = bracket
    state["jobs"][identifier] = job
    return identifier


def _bye(state, config, identifier, stage, tier, round_number, points=True):
    value = {**SCORE_DEFAULTS, **config.get("scoring", {})}["bye"] if points else 0
    if points:
        state["stats"][identifier]["byes"] += 1
        state["stats"][identifier]["points"] += value
    state["administrative"].append({"id": identifier, "stage": stage, "tier": tier,
                                    "round": round_number, "points": value, "wins": 0})


def _snapshot(state, config, cohort, played, tier, round_number):
    # All entries participate in normalization; only actual players earn an award.
    snapshot = score_snapshot([state["stats"][i] for i in cohort], config)
    for entry in snapshot["entries"]:
        if entry["id"] not in played:
            entry["contribution"] = 0
            entry["efficiency_points"] = state["stats"][entry["id"]]["efficiency_points"]
            entry["points"] = entry["base_points"] + entry["efficiency_points"]
    snapshot.update({"stage": state["stage"], "tier": tier, "round": round_number})
    return snapshot


def _finish_barrier(state, config):
    barrier = state["barrier"]
    if barrier["stage"] in ("round_robin", "swiss"):
        snapshots = []
        if barrier["stage"] == "round_robin":
            played = {state["jobs"][j][side] for j in barrier["jobs"] for side in ("a", "b")
                      if state["records"][j][side] != "F"}
            if barrier["jobs"]:
                snapshots.append(_snapshot(state, config, state["ids"], played, None, barrier["round"]))
        else:
            for tier, ids in state["tiers"].items():
                played = {state["jobs"][j][side] for j in barrier["jobs"]
                          if state["jobs"][j]["tier"] == tier for side in ("a", "b")
                          if state["records"][j][side] != "F"}
                if any(state["jobs"][j]["tier"] == tier for j in barrier["jobs"]):
                    snapshots.append(_snapshot(state, config, ids, played, tier, barrier["round"]))
        # Commit the barrier only after every cohort validated successfully.
        for snapshot in snapshots:
            for entry in snapshot["entries"]:
                stats = state["stats"][entry["id"]]
                stats["efficiency_points"] = entry["efficiency_points"]
                stats["points"] = entry["points"]
            state["snapshots"].append(snapshot)
        state["round"] += 1
    state["barrier"] = None


def _to_swiss(state, config):
    settings = _settings(config)
    # Remove worst failure/loss campaigns first. Low points break tied counts.
    worst = sorted(state["ids"], key=lambda i: (-state["stats"][i]["failures"],
                    -state["stats"][i]["losses"], state["stats"][i]["points"], _tie(state, i)))
    state["removed"] = worst[:settings["cut"]]
    remaining = [i for i in _rank(state, state["ids"]) if i not in set(state["removed"])]
    remaining.reverse()  # ascending points bands: iron through gold
    count, extra = divmod(len(remaining), len(settings["tiers"]))
    offset = 0
    for index, tier in enumerate(settings["tiers"]):
        size = count + (1 if index >= len(settings["tiers"]) - extra else 0)
        state["tiers"][tier] = remaining[offset:offset+size]
        offset += size
    state["stage_results"]["round_robin"] = deepcopy(state["stats"])
    state["stats"] = _new_stats(state["ids"])
    state["stage"] = "swiss"
    state["round"] = 0


def _pair_swiss(state, ids):
    """Globally minimize rematches, then campaign gaps, then strength gaps.

    An exact dynamic program is used for normal 20-entrant tiers. The tie order
    is seeded and stable; no global random state participates in pairing.
    """
    ordered = _rank(state, ids)
    strength = {i: _strength(state, i) for i in ordered}

    @lru_cache(None)
    def solve(mask):
        if not mask:
            return (0, 0, 0), ()
        first_bit = mask & -mask
        first = first_bit.bit_length() - 1
        rest = mask ^ first_bit
        best = None
        candidate_mask = rest
        while candidate_mask:
            bit = candidate_mask & -candidate_mask
            other = bit.bit_length() - 1
            candidate_mask ^= bit
            a, b = ordered[first], ordered[other]
            score, pairs = solve(rest ^ bit)
            edge = (state["stats"][a]["opponents"].count(b),
                    abs(state["stats"][a]["points"] - state["stats"][b]["points"]),
                    abs(strength[a] - strength[b]))
            candidate = (tuple(x+y for x, y in zip(score, edge)), ((a, b),) + pairs)
            if best is None or candidate[0] < best[0]:
                best = candidate
        return best

    return list(solve((1 << len(ordered)) - 1)[1])


def _eligible(state, settings, ids):
    return [i for i in ids if state["stats"][i]["losses"] + state["stats"][i]["failures"] < settings["swiss_strikes"]]


def _to_de(state, config):
    settings = _settings(config)
    state["stage_results"]["swiss"] = deepcopy(state["stats"])
    for tier, ids in state["tiers"].items():
        qualified = _rank(state, _eligible(state, settings, ids))[:settings["qualifiers"]]
        state["qualifiers"][tier] = qualified
        _make_bracket(state, tier, qualified)
    state["stats"] = _new_stats(state["ids"])
    state["stage"] = "double_elimination"
    state["round"] = 0


def _make_bracket(state, tier, ids):
    group = {"entrants": list(ids), "plan": [], "step": 0, "status": "running", "reset": False,
             "champion": None, "series_losses": {i: 0 for i in ids}}
    state["de"][tier] = group
    state["champions"][tier] = None
    if len(ids) < 2:
        group["status"] = "complete"
        group["champion"] = ids[0] if ids else None
        state["champions"][tier] = group["champion"]
        return
    size = 1 << (len(ids) - 1).bit_length()
    # Standard seed arrangement (1v8, 4v5, 2v7, 3v6 for eight).
    seed_order = [1, 2]
    while len(seed_order) < size:
        maximum = len(seed_order) * 2 + 1
        seed_order = [value for seed in seed_order for value in (seed, maximum - seed)]
    slots = [ids[seed - 1] if seed <= len(ids) else None for seed in seed_order]

    def wave(label, pairs, bracket):
        series_ids = []
        for index, (a, b) in enumerate(pairs):
            sid = f"{tier}:{label}:{index+1}"
            state["series"][sid] = {"id": sid, "tier": tier, "bracket": bracket,
                                    "a_ref": a, "b_ref": b, "a": None, "b": None,
                                    "status": "waiting", "games": [], "winner": None, "loser": None}
            series_ids.append(sid)
        group["plan"].append(series_ids)
        return series_ids

    def winner(sid):
        return {"winner": sid}

    def loser(sid):
        return {"loser": sid}

    def pair(values):
        return [(values[i], values[i+1] if i+1 < len(values) else None) for i in range(0, len(values), 2)]

    upper = wave("U1", pair(slots), "upper")
    lower = wave("L1", pair([loser(s) for s in upper]), "lower")
    round_number = 1
    while len(upper) > 1:
        round_number += 1
        upper = wave(f"U{round_number}", pair([winner(s) for s in upper]), "upper")
        lower = wave(f"L{2*round_number-2}", list(zip([winner(s) for s in lower], [loser(s) for s in reversed(upper)])), "lower")
        if len(upper) > 1:
            lower = wave(f"L{2*round_number-1}", pair([winner(s) for s in lower]), "lower")
    wave("G1", [(winner(upper[0]), winner(lower[0]))], "grand")


def _resolve_ref(state, value):
    if isinstance(value, dict):
        kind, sid = next(iter(value.items()))
        if state["series"][sid]["status"] not in ("complete", "bye"):
            raise RuntimeError("bracket dependency is not resolved")
        return state["series"][sid][kind]
    return value


def _series_scores(state, config, series):
    settings = {**SCORE_DEFAULTS, **config.get("scoring", {})}
    counts = {side: {"W": 0, "L": 0, "F": 0, "T": 0} for side in ("a", "b")}
    for mid in series["games"]:
        if mid in state["records"]:
            for side in counts:
                counts[side][state["records"][mid][side]] += 1
    scores = {side: sum(counts[side][v] * settings[k] for v, k in
                       (("W", "win"), ("L", "loss"), ("F", "failure"), ("T", "tie"))) for side in counts}
    keys = {side: (scores[side], -counts[side]["F"], counts[side]["W"]) for side in counts}
    return counts, scores, keys


def _complete_series(state, series, winner_side):
    loser_side = "b" if winner_side == "a" else "a"
    series["winner"], series["loser"] = series[winner_side], series[loser_side]
    series["status"] = "complete"
    group = state["de"][series["tier"]]
    group["series_losses"][series["loser"]] += 1
    if series["bracket"] == "grand":
        if winner_side == "b":
            group["reset"] = True
            sid = f"{series['tier']}:G2:1"
            state["series"][sid] = {"id": sid, "tier": series["tier"], "bracket": "reset",
                "a_ref": series["a"], "b_ref": series["b"], "a": None, "b": None,
                "status": "waiting", "games": [], "winner": None, "loser": None}
            group["plan"].append([sid])
        else:
            group["champion"] = series["winner"]
    elif series["bracket"] == "reset":
        group["champion"] = series["winner"]


def _de_jobs(state, config):
    settings = _settings(config)
    jobs = []
    for tier, group in state["de"].items():
        if group["status"] != "running":
            continue
        while group["step"] < len(group["plan"]):
            wave = group["plan"][group["step"]]
            for sid in wave:
                series = state["series"][sid]
                if series["status"] == "waiting":
                    series["a"] = _resolve_ref(state, series["a_ref"])
                    series["b"] = _resolve_ref(state, series["b_ref"])
                    if series["a"] is None or series["b"] is None:
                        series["status"] = "bye"
                        series["winner"] = series["a"] or series["b"]
                        if series["winner"]:
                            _bye(state, config, series["winner"], "double_elimination", tier, group["step"]+1, points=False)
                        continue
                    series["status"] = "running"
                if series["status"] != "running":
                    continue
                played = sum(mid in state["records"] for mid in series["games"])
                if played >= settings["series_games"]:
                    counts, scores, keys = _series_scores(state, config, series)
                    series["counts"], series["scores"] = counts, scores
                    if keys["a"] != keys["b"]:
                        _complete_series(state, series, "a" if keys["a"] > keys["b"] else "b")
                        continue
                    if played >= settings["series_games"] + settings["extra_games"] + series.get('extra_allowance',0):
                        series["status"] = "inconclusive"
                        group["status"] = "inconclusive"
                        break
                count = settings["series_games"] if not series["games"] else 1
                for _ in range(count):
                    mid = _job(state, series["a"], series["b"], "double_elimination", tier,
                               group["step"]+1, len(series["games"])+1, sid, series["bracket"])
                    series["games"].append(mid)
                    jobs.append(mid)
            if group["status"] == "inconclusive":
                break
            if all(state["series"][sid]["status"] in ("complete", "bye") for sid in wave):
                group["step"] += 1
                continue
            break
        if group["status"] == "running" and group["step"] >= len(group["plan"]):
            group["status"] = "complete"
            state["champions"][tier] = group["champion"]
    if all(g["status"] != "running" for g in state["de"].values()):
        state["status"] = "inconclusive" if any(g["status"] == "inconclusive" for g in state["de"].values()) else "complete"
    # A tied series can block its tier; discard newly constructed unrelated
    # series jobs in that same blocked tier before exposing them to the runner.
    active_jobs = [mid for mid in jobs if state["de"][state["jobs"][mid]["tier"]]["status"] == "running"]
    for mid in set(jobs) - set(active_jobs):
        sid = state["jobs"][mid]["series"]
        state["series"][sid]["games"].remove(mid)
        del state["jobs"][mid]
    return active_jobs


def next_matches(state, config):
    """Return currently outstanding jobs, advancing complete barriers in-place.

    Persist state after this call as well as after record_match. Repeated calls
    return identical pending IDs; results may arrive in any order. All state is
    ordinary JSON, including bracket dependencies and historical snapshots.
    """
    _check(state, config)
    settings = _settings(config)
    while state["status"] == "running":
        if state["barrier"] is not None:
            pending = [deepcopy(state["jobs"][mid]) for mid in state["barrier"]["jobs"] if mid not in state["records"]]
            if pending:
                return pending
            _finish_barrier(state, config)
        stage = state["stage"]
        jobs = []
        round_number = state["round"] + 1
        if stage == "round_robin":
            if state["round"] >= len(state["rr_schedule"]):
                _to_swiss(state, config)
                continue
            for a, b in state["rr_schedule"][state["round"]]:
                if a is None or b is None:
                    _bye(state, config, a or b, stage, None, round_number, points=False)
                else:
                    jobs.append(_job(state, a, b, stage, None, round_number))
        elif stage == "swiss":
            if state["round"] >= settings["swiss_rounds"]:
                _to_de(state, config)
                continue
            for tier, ids in state["tiers"].items():
                active = _eligible(state, settings, ids)
                if len(active) % 2:
                    ranked = _rank(state, active)
                    minimum = min(state["stats"][i]["byes"] for i in ranked)
                    bye = next(i for i in reversed(ranked) if state["stats"][i]["byes"] == minimum)
                    _bye(state, config, bye, stage, tier, round_number)
                    active.remove(bye)
                for a, b in _pair_swiss(state, active):
                    jobs.append(_job(state, a, b, stage, tier, round_number))
        else:
            jobs = _de_jobs(state, config)
            if state["status"] != "running":
                return []
        state["barrier"] = {"stage": stage, "round": round_number, "jobs": jobs}
        if jobs:
            return [deepcopy(state["jobs"][mid]) for mid in jobs]
    return []


def record_match(state, config, match_id, result):
    """Record one scheduled result in-place. Identical replay is idempotent."""
    _check(state, config)
    if match_id in state["records"]:
        if state["records"][match_id] != result:
            raise ValueError(f"conflicting duplicate result for {match_id}")
        return state
    if state["barrier"] is None or match_id not in state["barrier"]["jobs"]:
        raise ValueError(f"unknown or non-outstanding match {match_id}")
    job = state["jobs"][match_id]
    if not isinstance(result, dict) or any(result.get(side) not in COUNTS for side in ("a", "b")):
        raise ValueError("result must include a and b verdicts W/L/F/T")
    if (result['a'],result['b']) not in {('W','L'),('L','W'),('W','F'),('F','W'),('F','F'),('T','T')}:
        raise ValueError("inconsistent paired verdicts")
    metrics = result.get("metrics", {})
    if set(metrics) != {job["a"], job["b"]}:
        raise ValueError("result metrics must correspond exactly to scheduled competitors")
    normalized = {}
    for side in ("a", "b"):
        identifier = job[side]
        metric = deepcopy(metrics[identifier])
        if not isinstance(metric, dict) or metric.get("complete") is not (result[side] != "F"):
            raise ValueError("metric complete flag must match verdict (F is incomplete)")
        if metric["complete"]:
            # Validate unknown metrics now, before any state mutation.
            score_snapshot([{"id": identifier, "metrics": [metric]}], {"scoring": {"profile": "efficiency"}})
            if config.get("scoring", {}).get("profile") == "original":
                from scripts.arena_scoring import _number
                _number(metric.get("input_tokens"), "input_tokens")
                _number(metric.get("output_tokens"), "output_tokens")
        normalized[identifier] = metric
    json.dumps(result, allow_nan=False)
    state["records"][match_id] = deepcopy(result)
    for side, other in (("a", "b"), ("b", "a")):
        stats = state["stats"][job[side]]
        stats[COUNTS[result[side]]] += 1
        stats["metrics"].append(normalized[job[side]])
        stats["opponents"].append(job[other])
        if job["stage"] == "double_elimination":
            settings = {**SCORE_DEFAULTS, **config.get("scoring", {})}
            stats["points"] += settings[{"W": "win", "L": "loss", "F": "failure", "T": "tie"}[result[side]]]
    return state


def report(state):
    """Return a detached summary safe to serialize or edit."""
    series = [s for s in state["series"].values() if s["games"]]
    return deepcopy({"status": state["status"], "stage": state["stage"], "round": state["round"],
                     "entrants": len(state["ids"]), "matches": len(state["records"]),
                     "removed": state["removed"], "tiers": state["tiers"], "qualifiers": state["qualifiers"],
                     "champions": state["champions"], "series_played": len(series),
                     "inconclusive_series": [s["id"] for s in series if s["status"] == "inconclusive"],
                     "snapshots": len(state["snapshots"]), "administrative_byes": len(state["administrative"])})


def reopen_inconclusive(state, config, extra_games):
    """Authorize a finite additional allowance per unresolved series in-place.

    The frozen configuration and historical records remain unchanged. A caller
    must explicitly supply a positive integer; no automatic extension occurs.
    """
    _check(state,config)
    if type(extra_games) is not int or extra_games <= 0:
        raise ValueError('Additional extra_games must be a positive integer')
    unresolved = [s for s in state['series'].values() if s['status'] == 'inconclusive']
    if state['stage'] != 'double_elimination' or state['status'] != 'inconclusive' or not unresolved:
        raise ValueError('No inconclusive series exists to reopen')
    amendment = {'index':len(state.get('amendments',[]))+1,'kind':'explicit_extra_games',
                 'extra_games':extra_games,'series':[s['id'] for s in unresolved],
                 'previous':{s['id']:{'games':len(s['games']),'extra_allowance':s.get('extra_allowance',0),
                                     'scores':deepcopy(s.get('scores'))} for s in unresolved}}
    for series in unresolved:
        series['extra_allowance'] = series.get('extra_allowance',0)+extra_games
        series['status'] = 'running'
        state['de'][series['tier']]['status'] = 'running'
    state.setdefault('amendments',[]).append(amendment)
    state['status'] = 'running'
    state['barrier'] = None
    return state
