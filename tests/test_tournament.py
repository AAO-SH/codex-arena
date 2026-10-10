import copy
import json
import pytest

from scripts import arena_tournament as arena


def config(n=100, **options):
    return {"seed": 7, "tournament": {"entrants": n, "cut": 20 if n == 100 else 0,
            "tiers": ["iron", "copper", "silver", "gold"], "swiss_rounds": 5,
            "swiss_strikes": 4, "qualifiers": 8, "series_games": 10, "extra_games": 5, **options}}


def entrants(n):
    return [{"id": f"c{i:03}"} for i in range(n)]


def result(job, a="W", b="L"):
    return {"a": a, "b": b, "metrics": {p: {"elapsed_ms": 10, "cost_usd": .01,
                "input_tokens": 100, "output_tokens": 100, "complete": v != "F"}
                for p, v in ((job["a"], a), (job["b"], b))}, "evidence": []}


def drive(state, cfg, decide=None, limit=20000):
    seen = []
    for _ in range(limit):
        jobs = arena.next_matches(state, cfg)
        if not jobs:
            assert state["status"] in ("complete", "inconclusive")
            return seen
        for job in jobs:
            outcome = decide(job) if decide else ("W", "L")
            arena.record_match(state, cfg, job["id"], result(job, *outcome))
            seen.append(job)
    pytest.fail("engine did not terminate")


def test_complete_100_entrant_round_robin_swiss_and_four_champions():
    cfg = config()
    state = arena.create_tournament(cfg, entrants(100))
    first = arena.next_matches(state, cfg)
    assert len(first) == 50
    seen = drive(state, cfg)
    rr = [j for j in seen if j["stage"] == "round_robin"]
    assert len(rr) == 4950
    assert len({tuple(sorted((j["a"], j["b"]))) for j in rr}) == 4950
    assert len({j["round"] for j in rr}) == 99
    assert len(state["removed"]) == 20
    assert {t: len(ids) for t, ids in state["tiers"].items()} == {t: 20 for t in cfg["tournament"]["tiers"]}
    assert set(arena.report(state)["champions"]) == set(cfg["tournament"]["tiers"])
    assert all(arena.report(state)["champions"].values())
    assert json.loads(json.dumps(state)) == state


def test_duplicate_records_idempotent_and_conflicting_or_unknown_rejected():
    cfg = config(4)
    state = arena.create_tournament(cfg, entrants(4))
    job = arena.next_matches(state, cfg)[0]
    outcome = result(job)
    arena.record_match(state, cfg, job["id"], outcome)
    frozen = copy.deepcopy(state)
    arena.record_match(state, cfg, job["id"], outcome)
    assert state == frozen
    with pytest.raises(ValueError, match="conflict"):
        arena.record_match(state, cfg, job["id"], result(job, "L", "W"))
    with pytest.raises(ValueError):
        arena.record_match(state, cfg, "unknown", outcome)


def test_barrier_snapshots_do_not_rewrite_history_and_stage_points_reset():
    cfg = config(4, tiers=["gold"])
    state = arena.create_tournament(cfg, entrants(4))
    jobs = arena.next_matches(state, cfg)
    arena.record_match(state, cfg, jobs[0]["id"], result(jobs[0]))
    assert state["snapshots"] == []
    assert len(arena.next_matches(state, cfg)) == 1
    arena.record_match(state, cfg, jobs[1]["id"], result(jobs[1]))
    arena.next_matches(state, cfg)
    old = copy.deepcopy(state["snapshots"][0])
    while state["stage"] == "round_robin":
        jobs = arena.next_matches(state, cfg)
        if state["stage"] != "round_robin":
            break
        for job in jobs:
            arena.record_match(state, cfg, job["id"], result(job))
    assert state["snapshots"][0] == old
    assert all(x["wins"] == x["losses"] == x["efficiency_points"] == 0 for x in state["stats"].values())


def test_swiss_strikes_count_losses_plus_failures_and_byes_never_win():
    cfg = config(5, tiers=["gold"], swiss_rounds=5, swiss_strikes=2)
    state = arena.create_tournament(cfg, entrants(5))
    seen = drive(state, cfg, lambda j: ("F", "W") if j["stage"] == "swiss" else ("W", "L"))
    swiss = [j for j in seen if j["stage"] == "swiss"]
    totals = {}
    for j in swiss:
        totals[j["a"]] = totals.get(j["a"], 0) + 1
    assert max(totals.values()) <= 2
    bye_records = [b for b in state["administrative"] if b["stage"] == "swiss"]
    assert bye_records and all(b["points"] == 3 and b["wins"] == 0 for b in bye_records)


def test_eight_entrant_double_elimination_bracket_reset_has_fifteen_series():
    cfg = config(8, tiers=["gold"], swiss_rounds=0)
    state = arena.create_tournament(cfg, entrants(8))
    seen = drive(state, cfg, lambda j: ("L", "W") if j.get("bracket") == "grand" else ("W", "L"))
    de = [j for j in seen if j["stage"] == "double_elimination"]
    assert len({j["series"] for j in de}) == 15
    assert len(de) == 150
    assert state["de"]["gold"]["reset"] is True


def test_series_tiebreak_failure_then_wins_and_finite_extra_game_inconclusive():
    cfg = config(2, tiers=["gold"], swiss_rounds=0)
    state = arena.create_tournament(cfg, entrants(2))
    seen = drive(state, cfg, lambda j: ("T", "T"))
    de = [j for j in seen if j["stage"] == "double_elimination"]
    assert len(de) == 15
    assert state["status"] == "inconclusive"
    assert arena.report(state)["champions"]["gold"] is None


@pytest.mark.parametrize("n", [0, 1])
def test_zero_and_single_entrant_do_not_fabricate_games(n):
    cfg = config(n, tiers=["gold"], swiss_rounds=0)
    state = arena.create_tournament(cfg, entrants(n))
    assert drive(state, cfg) == []
    assert arena.report(state)["champions"]["gold"] == ("c000" if n else None)


@pytest.mark.parametrize("n", range(2, 9))
def test_double_elimination_padding_byes_preserve_actual_series_count(n):
    cfg = config(n, tiers=["gold"], swiss_rounds=0)
    state = arena.create_tournament(cfg, entrants(n))
    seen = drive(state, cfg)
    de = [j for j in seen if j["stage"] == "double_elimination"]
    assert len({j["series"] for j in de}) == 2 * n - 2
    assert len(de) == 10 * (2 * n - 2)
    assert state["de"]["gold"]["series_losses"][state["champions"]["gold"]] == 0
    assert sum(v == 2 for v in state["de"]["gold"]["series_losses"].values()) == n - 1


def test_mid_round_json_resume_preserves_pending_jobs_and_scores():
    cfg = config(8, tiers=["gold"])
    state = arena.create_tournament(cfg, entrants(8))
    jobs = arena.next_matches(state, cfg)
    arena.record_match(state, cfg, jobs[0]["id"], result(jobs[0]))
    resumed = json.loads(json.dumps(state))
    assert arena.next_matches(resumed, cfg) == arena.next_matches(state, cfg)
    drive(resumed, cfg)
    drive(state, cfg)
    assert resumed == state


def test_result_with_wrong_competitors_or_missing_complete_cost_is_atomic():
    cfg = config(2, tiers=["gold"])
    state = arena.create_tournament(cfg, entrants(2))
    job = arena.next_matches(state, cfg)[0]
    old = copy.deepcopy(state)
    bad = result(job)
    bad["metrics"][job["a"]]["cost_usd"] = None
    with pytest.raises(ValueError, match="cost_usd"):
        arena.record_match(state, cfg, job["id"], bad)
    assert state == old
    bad = result(job)
    bad["metrics"]["intruder"] = bad["metrics"].pop(job["a"])
    with pytest.raises(ValueError, match="scheduled"):
        arena.record_match(state, cfg, job["id"], bad)
    assert state == old


def test_swiss_pairing_globally_minimizes_rematches():
    cfg = config(6, tiers=["gold"])
    state = arena.create_tournament(cfg, entrants(6))
    # Naive first-choice greedy pairing a/b leaves e/f as a rematch.
    for a, b in [("c004", "c005")]:
        state["stats"][a]["opponents"].append(b)
        state["stats"][b]["opponents"].append(a)
    pairs = arena._pair_swiss(state, state["ids"])
    assert len(pairs) == 3
    assert not any(b in state["stats"][a]["opponents"] for a, b in pairs)


def test_failed_cohort_snapshot_does_not_partially_commit_other_tiers():
    cfg = config(4, tiers=["iron", "gold"])
    state = arena.create_tournament(cfg, entrants(4))
    while state["stage"] == "round_robin":
        jobs = arena.next_matches(state, cfg)
        if state["stage"] != "round_robin":
            break
        for job in jobs:
            arena.record_match(state, cfg, job["id"], result(job))
    first_swiss = jobs
    for job in first_swiss:
        arena.record_match(state, cfg, job["id"], result(job))
    second_swiss = arena.next_matches(state, cfg)
    for job in second_swiss:
        outcome = result(job, "F", "W") if job["tier"] == "gold" else result(job)
        if job["tier"] == "gold":
            outcome["metrics"][job["a"]]["cost_usd"] = None
        arena.record_match(state, cfg, job["id"], outcome)
    before = copy.deepcopy(state)
    with pytest.raises(ValueError, match="cost_usd"):
        arena.next_matches(state, cfg)
    assert state == before


def test_de_game_points_are_base_only_and_series_failure_tie_break_wins():
    cfg = config(2, tiers=["gold"], swiss_rounds=0)
    state = arena.create_tournament(cfg, entrants(2))
    while state["stage"] != "double_elimination":
        jobs = arena.next_matches(state, cfg)
        if state["stage"] == "double_elimination":
            break
        for job in jobs:
            arena.record_match(state, cfg, job["id"], result(job))
    schedule = [("L", "W")] * 4 + [("W", "F")] * 3 + [("T", "T")] * 3
    for job, pair in zip(jobs, schedule):
        arena.record_match(state, cfg, job["id"], result(job, *pair))
    arena.next_matches(state, cfg)
    first_series = state["series"][jobs[0]["series"]]
    assert first_series["scores"] == {"a": -3, "b": -3}
    assert first_series["winner"] == jobs[0]["a"]
    assert state["stats"][jobs[0]["a"]]["points"] == -3
    assert state["stats"][jobs[0]["a"]]["efficiency_points"] == 0


def test_ranking_prioritizes_failures_and_wins_before_opponent_strength():
    cfg = config(4, tiers=["gold"])
    state = arena.create_tournament(cfg, entrants(4))
    a, b, c, d = state["ids"]
    state["stats"][a].update({"points": 3, "failures": 0, "wins": 1, "opponents": [d]})
    state["stats"][b].update({"points": 3, "failures": 1, "wins": 5, "opponents": [c]})
    state["stats"][c]["points"] = 100
    assert arena._rank(state, [a, b]) == [a, b]
    state["stats"][b]["failures"] = 0
    state["stats"][a]["wins"] = 6
    assert arena._rank(state, [a, b]) == [a, b]


def test_original_calibration_is_required_before_any_task_is_scheduled():
    cfg = config(2, tiers=["gold"])
    cfg["scoring"] = {"profile": "original"}
    with pytest.raises(ValueError, match="calibration"):
        arena.create_tournament(cfg, entrants(2))


def test_current_round_failure_has_no_historical_efficiency_bonus():
    cfg = config(4, tiers=["gold"])
    state = arena.create_tournament(cfg, entrants(4))
    first = arena.next_matches(state, cfg)
    target = first[0]["a"]
    for job in first:
        outcome = result(job)
        for cid, metric in outcome["metrics"].items():
            metric["elapsed_ms"] = 1 if cid == target else 10
            metric["cost_usd"] = .001 if cid == target else .01
        arena.record_match(state, cfg, job["id"], outcome)
    second = arena.next_matches(state, cfg)
    for job in second:
        pair = ("F", "W") if job["a"] == target else ("W", "F") if job["b"] == target else ("W", "L")
        arena.record_match(state, cfg, job["id"], result(job, *pair))
    arena.next_matches(state, cfg)
    row = next(x for x in state["snapshots"][-1]["entries"] if x["id"] == target)
    assert row["contribution"] == 0
    assert row["efficiency_points"] == 3


def test_series_most_wins_decides_after_equal_scores_and_failures():
    cfg = config(2, tiers=["gold"], swiss_rounds=0)
    cfg["scoring"] = {"win": 0, "loss": 0}
    state = arena.create_tournament(cfg, entrants(2))
    drive(state, cfg)
    first = next(s for s in state["series"].values() if s["bracket"] == "upper")
    assert first["scores"] == {"a": 0, "b": 0}
    assert first["winner"] == first["a"]


def test_swiss_four_strikes_combine_separate_failure_and_loss_counts():
    cfg = config(8, tiers=["gold"], swiss_rounds=6, swiss_strikes=4)
    state = arena.create_tournament(cfg, entrants(8))
    target = "c000"
    def decide(job):
        if job["stage"] != "swiss" or target not in (job["a"], job["b"]):
            return "W", "L"
        loss = "F" if job["round"] % 2 else "L"
        return (loss, "W") if job["a"] == target else ("W", loss)
    seen = drive(state, cfg, decide)
    played = [j for j in seen if j["stage"] == "swiss" and target in (j["a"], j["b"])]
    final = state["stage_results"]["swiss"][target]
    assert len(played) == 4
    assert final["failures"] == 2 and final["losses"] == 2
    assert target not in state["qualifiers"]["gold"]


@pytest.mark.parametrize('pair',[('L','L'),('L','F'),('F','L'),('W','W'),('T','F')])
def test_paired_verdicts_cannot_invent_losses_or_ties(pair):
    cfg = config(2,tiers=['gold'])
    state = arena.create_tournament(cfg,entrants(2))
    job = arena.next_matches(state,cfg)[0]
    old = copy.deepcopy(state)
    with pytest.raises(ValueError,match='paired'):
        arena.record_match(state,cfg,job['id'],result(job,*pair))
    assert state == old


def test_explicit_extra_allowance_can_reopen_and_finish_inconclusive_series():
    cfg = config(2,tiers=['gold'],swiss_rounds=0)
    state = arena.create_tournament(cfg,entrants(2))
    drive(state,cfg,lambda j: ('T','T'))
    assert state['status'] == 'inconclusive'
    historical = copy.deepcopy(state['snapshots'])
    prior_records = copy.deepcopy(state['records'])
    fingerprint = state['config_fingerprint']
    arena.reopen_inconclusive(state,cfg,2)
    assert state['status'] == 'running'
    assert arena.report(state)['champions']['gold'] is None
    drive(state,cfg)
    assert state['status'] == 'complete' and state['champions']['gold']
    assert state['snapshots'] == historical and state['config_fingerprint'] == fingerprint
    assert all(state['records'][mid] == result for mid,result in prior_records.items())
    assert state['amendments'][0]['extra_games'] == 2


def test_explicit_extra_allowance_remains_bounded_if_ties_continue():
    cfg = config(2,tiers=['gold'],swiss_rounds=0)
    state = arena.create_tournament(cfg,entrants(2))
    drive(state,cfg,lambda j: ('T','T'))
    with pytest.raises(ValueError):
        arena.reopen_inconclusive(state,cfg,0)
    arena.reopen_inconclusive(state,cfg,2)
    added = drive(state,cfg,lambda j: ('T','T'))
    assert len(added) == 2 and state['status'] == 'inconclusive'
    assert state['champions']['gold'] is None
