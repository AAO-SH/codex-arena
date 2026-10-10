import copy
import pytest
from scripts import arena_config as config


def test_defaults_validate_and_do_not_share_mutable_state():
    rules = config.load_config()
    assert rules['tournament']['entrants'] == 100
    assert rules['tournament']['series_games'] == 10
    rules['models']['policy'].clear()
    assert len(config.load_config()['models']['policy']) == 3


def test_invalid_tiers_and_unknown_fields_rejected():
    rules = config.load_config()
    rules['tournament']['cut'] = 99
    with pytest.raises(ValueError):
        config.validate_config(rules)
    rules = config.load_config()
    rules['executoon'] = {}
    with pytest.raises(ValueError):
        config.validate_config(rules)


def test_cases_do_not_mix_holdout_in_training(tmp_path):
    cases = {'schema_version': 1, 'family': 'test', 'cases': [
        {'id': 'a', 'prompt': 'task', 'split': 'train'},
        {'id': 'b', 'prompt': 'unseen', 'split': 'holdout'}]}
    rules = config.load_config()
    rules['validation']['min_train'] = rules['validation']['min_holdout'] = 1
    result = config.validate_cases(cases, rules)
    assert result['cases'][0]['id'] == 'a'
    cases['cases'][1]['id'] = 'a'
    with pytest.raises(ValueError, match='unique|duplic'):
        config.validate_cases(cases, rules)
