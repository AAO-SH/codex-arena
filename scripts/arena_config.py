"""Validated, frozen-per-run contracts. Configuration is data, never executable code."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EFFORTS = ('low', 'medium', 'high', 'xhigh', 'max', 'ultra')


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def read_json(path: Path | str) -> Any:
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def atomic_json(path: Path | str, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    import uuid
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temp.open('wb') as stream:
            stream.write(canonical(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def contained(root: Path | str, relative: str) -> Path:
    root = Path(root).resolve()
    # Reject Windows-style traversal even when validation runs on POSIX.
    if not relative or '\\' in relative or ':' in relative:
        raise ValueError(f'Unsafe relative path: {relative!r}')
    path = (root / relative).resolve()
    if Path(relative).is_absolute() or not path.is_relative_to(root) or path == root:
        raise ValueError(f'Path escapes workspace: {relative!r}')
    return path


def _shape(value: Any) -> dict:
    if isinstance(value, bool):
        return {'type': 'boolean'}
    if isinstance(value, int):
        return {'type': 'integer'}
    if isinstance(value, float):
        return {'type': 'number'}
    if isinstance(value, str):
        return {'type': 'string'}
    if value is None:
        return {'type': ['object', 'null']}
    if isinstance(value, list):
        return {'type': 'array', 'items': _shape(value[0]) if value else {'type': 'string'}}
    return {'type': 'object', 'properties': {k: _shape(v) for k, v in value.items()},
            'required': list(value), 'additionalProperties': False}


def config_schema() -> dict:
    defaults = read_json(ROOT / 'assets/default-config.json')
    schema = _shape(defaults)
    schema.update({'$schema': 'https://json-schema.org/draft/2020-12/schema',
                   'title': 'Codex Arena configuration v1'})
    schema['properties']['schema_version'] = {'const': 1}
    pricing = {'type': 'object', 'properties': {k: {'type': 'number', 'minimum': 0}
               for k in ('input', 'cached_input', 'output')},
               'required': ['input', 'cached_input', 'output'], 'additionalProperties': False}
    schema['properties']['prices'] = {'type': 'object', 'additionalProperties': pricing}
    for section, fields in {'tournament': ('entrants','swiss_rounds','swiss_strikes','qualifiers','series_games'),
                            'execution': ('concurrency','job_timeout_ms','reservation_tokens','max_output_chars'),
                            'validation': ('min_train','min_holdout','repetitions'),
                            'memory': ('topk','context_token_budget')}.items():
        for field in fields:
            schema['properties'][section]['properties'][field]['minimum'] = 1
    schema['properties']['scoring']['properties']['profile'] = {'enum': ['efficiency','original']}
    # Weights/points may be fractional even when defaults are integer-valued.
    for field in ('win','loss','failure','tie','bye','speed_weight','expense_weight'):
        schema['properties']['scoring']['properties'][field] = {'type': 'number'}
    return schema


def validate_config(rules: dict) -> dict:
    from jsonschema import Draft202012Validator
    errors = sorted(Draft202012Validator(config_schema()).iter_errors(rules), key=lambda e: str(e.path))
    if errors:
        raise ValueError('; '.join(f'{list(e.path)}: {e.message}' for e in errors[:8]))
    t = rules['tournament']
    remaining = t['entrants'] - t['cut']
    if t['cut'] < 0 or remaining < 4 or remaining % 4:
        raise ValueError('entrants - cut must be a positive multiple of four, at least four')
    if t['tiers'] != ['iron','copper','silver','gold']:
        raise ValueError('tiers must be iron, copper, silver, gold in ascending order')
    if t['qualifiers'] > remaining // 4 or t['qualifiers'] & (t['qualifiers'] - 1):
        raise ValueError('qualifiers must be a power of two no greater than tier size')
    if t['extra_games'] < 0 or rules['execution']['max_escalations'] < 0:
        raise ValueError('negative retry/extra-game limits are invalid')
    if rules['execution']['sandbox'] not in ('read-only', 'workspace-write'):
        raise ValueError('sandbox must be read-only or workspace-write')
    for pair in rules['models']['policy'] + [rules['models']['judge'],rules['models']['arbiter']]:
        if not pair['model'].strip() or pair['effort'] not in EFFORTS:
            raise ValueError(f'Invalid model/effort: {pair}')
    if not rules['models']['policy']:
        raise ValueError('At least one execution model is required')
    if not 0 <= rules['validation']['resource_gain'] < 1:
        raise ValueError('resource_gain must be >= zero and < one')
    if rules['validation']['quality_gain'] < 0 or rules['execution']['infrastructure_retries'] < 0 or rules['execution']['retry_backoff_ms'] < 0:
        raise ValueError('Negative promotion/retry limits are invalid')
    if rules['plugins']['require_semantic_review'] is not True:
        raise ValueError('Semantic plugin review is a required invariant')
    if any(v < 0 for v in rules['rubric'].values()) or sum(rules['rubric'].values()) <= 0:
        raise ValueError('rubric needs nonnegative weights and a positive sum')
    canonical(rules)  # rejects NaN/Infinity
    return copy.deepcopy(rules)


def load_config(path: Path | str | None = None) -> dict:
    return validate_config(read_json(path or ROOT / 'assets/default-config.json'))


def validate_cases(data: dict, rules: dict) -> dict:
    from jsonschema import Draft202012Validator
    schema = read_json(ROOT/'schemas/cases.schema.json')
    errors = list(Draft202012Validator(schema).iter_errors(data))
    if errors:
        raise ValueError('Invalid case suite: '+errors[0].message)
    if data.get('schema_version') != 1 or not isinstance(data.get('family'), str):
        raise ValueError('case suite requires schema_version=1 and family')
    cases = data.get('cases', [])
    ids = [c.get('id') for c in cases]
    if len(ids) != len(set(ids)):
        raise ValueError('case ids must be unique; duplicate id found')
    for case in cases:
        if not isinstance(case.get('id'), str) or not case['id'] or not isinstance(case.get('prompt'), str) or not case['prompt'].strip():
            raise ValueError('Every case needs a nonempty id and prompt')
        if case.get('split') not in ('train','holdout'):
            raise ValueError('split must be train or holdout')
        completion = case.get('completion', {})
        for path in completion.get('required_files', []):
            contained(Path.cwd(), path)
        for check in completion.get('checks', []):
            if not isinstance(check, list) or not check or not all(isinstance(x,str) for x in check):
                raise ValueError('checks are argv arrays, never shell strings')
    for split, key in [('train','min_train'),('holdout','min_holdout')]:
        if sum(c['split'] == split for c in cases) < rules['validation'][key]:
            raise ValueError(f'Need at least {rules["validation"][key]} {split} cases')
    return copy.deepcopy(data)
