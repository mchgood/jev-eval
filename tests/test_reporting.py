import json
from pathlib import Path

import pytest

from jev_eval.cli import main
from jev_eval.metrics import summarize
from jev_eval.reporting import write_reports
from jev_eval.schema import load_cases

DATA = Path(__file__).parents[1] / 'data/smoke.jsonl'


def result(case, answer=None, latency=10):
    return {'case': case.model_dump(), 'status': 'ok' if answer else 'error',
            'latency_ms': latency, 'raw': {'answers': {'decision': answer}}}


def test_pass_denominator_unknown_errors_and_failed_request_timing():
    cases = load_cases(DATA)
    known = next(c for c in cases if c.question['type'] == 'noul' and c.gold is True)
    unknown = next(c for c in cases if c.gold is None)
    rows = [result(known, {'noul': 0.7}), result(known, latency=100),
            result(unknown, {'noul': 0.8}, latency=20)]
    data = summarize(rows, 0.5)
    stats = data['overview']
    assert stats['pass_rate'] == 0.5
    assert stats['request_success_rate'] == pytest.approx(2 / 3)
    assert stats['excluded_unknown'] == 1
    assert stats['latency_ms']['total'] == 130
    assert stats['latency_ms']['mean'] == pytest.approx(130 / 3)
    assert len(data['failures']) == 1
    assert summarize([], 0.5)['overview']['pass_rate'] is None
    assert summarize([result(unknown)], 0.5)['overview']['pass_rate'] is None


def test_score_pass_uses_probability_level_not_rounded_expectation():
    case = next(c for c in load_cases(DATA) if c.question['type'] == 'score' and c.gold == 3)
    data = summarize([result(case, {'score': 2.1, 'probabilities': {'0': 0.3, '3': 0.7}})], 0.5)
    assert data['overview']['pass_rate'] == 1
    assert data['groups'][0]['mae'] == pytest.approx(0.9)


def test_report_regeneration_reads_manifest_and_escapes_cases(tmp_path, monkeypatch):
    case = load_cases(DATA)[0]
    row = result(case, latency=50)
    row['error_message'] = '<script>alert(1)</script>|broken\nline'
    results = tmp_path / 'results.jsonl'
    results.write_text(json.dumps(row) + '\n')
    (tmp_path / 'manifest.json').write_text(json.dumps({'model': 'test', 'elapsed_seconds': 2}))
    output = tmp_path / 'report'
    monkeypatch.setattr('sys.argv', ['jev-eval', 'report', '--results', str(results), '--out', str(output)])
    main()
    summary = json.loads((output / 'summary.json').read_text())
    assert summary['run']['elapsed_seconds'] == 2
    assert summary['overview']['pass_rate'] == 0
    html = (output / 'report.html').read_text()
    assert '<script>' not in html
    assert '&lt;script&gt;' in html
    assert '0.00%' in html
    assert len(json.loads((output / 'failures.json').read_text())) == 1
    assert 'P95' in (output / 'report.md').read_text()


def test_run_reports_api_errors_and_records_wall_time(tmp_path, monkeypatch):
    from jev_eval import cli

    class FailingBackend:
        def __init__(self, *args):
            pass

        def evaluate(self, case):
            raise RuntimeError('service unavailable')

        def close(self):
            pass

    monkeypatch.setattr(cli, 'JevBackend', FailingBackend)
    monkeypatch.setenv('TYPESAFE_API_KEY', 'test')
    output = tmp_path / 'run'
    monkeypatch.setattr('sys.argv', ['jev-eval', 'run', '--data', str(DATA), '--out', str(output)])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    summary = json.loads((output / 'summary.json').read_text())
    assert summary['overview']['failed'] == 17
    assert summary['overview']['pass_rate'] == 0
    assert summary['run']['completed_cases'] == 17
    assert summary['run']['elapsed_seconds'] > 0
    assert summary['run']['ended_at']
    assert (output / 'report.html').exists()


def test_empty_report(tmp_path):
    write_reports(tmp_path, summarize([], 0.5))
    assert '—' in (tmp_path / 'report.md').read_text()
