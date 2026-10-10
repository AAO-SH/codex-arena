import json
from pathlib import Path
from jsonschema import Draft202012Validator
from scripts.arena_config import ROOT, load_config, validate_cases
from scripts.build_contracts import contracts
from scripts.arena_runner import make_competitors
from scripts.arena_tournament import create_tournament, next_matches


def test_published_schemas_are_valid_and_current():
    for path in (ROOT/'schemas').glob('*.json'):
        Draft202012Validator.check_schema(json.loads(path.read_text(encoding='utf-8')))
    for name,schema in contracts().items():
        assert json.loads((ROOT/'schemas'/f'{name}.schema.json').read_text(encoding='utf-8')) == schema


def test_examples_and_produced_job_conform():
    schemas=contracts()
    config=load_config(ROOT/'examples/rules-smoke.json')
    Draft202012Validator(schemas['config']).validate(config)
    suite=json.loads((ROOT/'examples/demo-suite.json').read_text(encoding='utf-8'))
    validate_cases(suite,config)
    Draft202012Validator(schemas['cases']).validate(suite)
    competitors=make_competitors(config)
    for comp in competitors:
        Draft202012Validator(schemas['competitor']).validate(comp)
    state=create_tournament(config,competitors)
    for job in next_matches(state,config): Draft202012Validator(schemas['job']).validate(job)
