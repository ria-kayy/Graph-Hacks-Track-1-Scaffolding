import json
from types import SimpleNamespace

import pytest
from backend.agent import planner
from backend.agent.toolbox import dispatch


def test_tool_arguments_cannot_inject_repository_cypher_or_shell():
    for name, args in [
        ('shell', {'command': 'rm -rf /'}),
        ('search_code', {'query': 'retry', 'repo_id': 'other'}),
        ('search_code', {'query': 'retry', 'limit': 50000}),
        ('history', {'symbol': 'retry', 'cypher': 'MATCH (n) DELETE n'}),
    ]:
        with pytest.raises(ValueError):
            dispatch('repo-a', None, name, args)


class Provider:
    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.requests = []
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def post(self, url, **kwargs):
        self.requests.append(json.loads(json.dumps(kwargs['json'])))
        output = next(self.outputs)
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'output': output})


def setup_provider(monkeypatch, outputs):
    monkeypatch.setenv('LLM_API_KEY', 'test-key')
    monkeypatch.setenv('LLM_MODEL', 'configured-test-model')
    provider = Provider(outputs)
    monkeypatch.setattr(planner.httpx, 'Client', lambda **kwargs: provider)
    return provider


def test_model_selects_validated_tools_then_cites_retrieved_evidence(monkeypatch):
    evidence = {'evidence_id': 'source-1', 'evidence_type': 'source', 'excerpt': 'untrusted source'}
    provider = setup_provider(monkeypatch, [
        [{'type': 'function_call', 'name': 'read_source', 'call_id': '1', 'arguments': json.dumps({'file_path': 'a.py', 'purpose': 'Verify the implementation before answering.'})}],
        [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps({'answer': 'Inspect this source. Cause is unverified.', 'citations': ['source-1']})}]}],
    ])
    calls = []
    monkeypatch.setattr(planner, 'dispatch', lambda *args: calls.append(args) or evidence)
    result = planner.run('repo-a', 'what calls it?', '2020-01-01T00:00:00Z', [], [])
    assert result['tools'] == ['read_source']
    assert calls[0][:3] == ('repo-a', '2020-01-01T00:00:00Z', 'read_source')
    assert result['evidence'] == [evidence]
    assert calls[0][3] == {'file_path': 'a.py'}
    step = result['execution']['steps'][0]
    assert step['purpose'] == 'Verify the implementation before answering.'
    assert step['status'] == 'completed'
    assert json.loads(step['result']) == evidence
    assert step['evidence_ids'] == ['source-1']
    assert result['execution']['status'] == 'completed'
    assert 'untrusted' in provider.requests[0]['instructions']


def test_model_tool_loop_stops_at_budget(monkeypatch):
    outputs = [[{'type': 'function_call', 'name': 'history', 'call_id': str(n), 'arguments': '{"symbol":"retry"}'}] for n in range(20)]
    provider = setup_provider(monkeypatch, outputs)
    calls = []
    monkeypatch.setattr(planner, 'dispatch', lambda *args: calls.append(args) or {})
    result = planner.run('repo-a', 'why retry?', None, [], [])
    assert result['answer'] is None
    assert result['execution']['status'] == 'budget_reached'
    assert result['execution']['steps']
    assert len(calls) <= planner.MAX_TOOL_CALLS
    assert len(provider.requests) <= planner.MAX_ROUNDS


@pytest.mark.parametrize('answer,citations', [
    ('Invented explanation', ['fabricated-id']),
    ('See https://evil.example/fake-proof', ['source-1']),
])
def test_model_cannot_supply_new_evidence_or_urls(monkeypatch, answer, citations):
    setup_provider(monkeypatch, [[{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps({'answer': answer, 'citations': citations})}]}]])
    result = planner.run('repo-a', 'why?', None, [{'evidence_id': 'source-1'}], [])
    assert result['answer'] is None
    assert result['execution']['status'] == 'failed'
    assert 'verification' in result['execution']['stop_reason']


def test_failed_tool_is_visible_and_model_can_choose_a_different_tool(monkeypatch):
    evidence = {'evidence_id': 'source-1', 'evidence_type': 'source', 'excerpt': 'verified source'}
    provider = setup_provider(monkeypatch, [
        [{'type': 'function_call', 'name': 'history', 'call_id': '1', 'arguments': '{"symbol":"missing"}'}],
        [{'type': 'function_call', 'name': 'read_source', 'call_id': '2', 'arguments': '{"file_path":"a.py","purpose":"Read source after history was unavailable."}'}],
        [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps({'answer': 'Inspect source; cause is unverified.', 'citations': ['source-1']})}]}],
    ])
    def execute(repo, cutoff, name, args):
        if name == 'history':
            raise ValueError('private error must not be shown')
        return evidence
    monkeypatch.setattr(planner, 'dispatch', execute)
    result = planner.run('repo-a', 'why?', None, [], [])
    assert [s['status'] for s in result['execution']['steps']] == ['failed', 'completed']
    assert [s['tool'] for s in result['execution']['steps']] == ['history', 'read_source']
    assert 'private error' not in json.dumps(result)
    assert provider.requests[1]['input'][-1]['type'] == 'function_call_output'
    assert 'error' in provider.requests[1]['input'][-1]['output']


def test_provider_failure_preserves_executed_tools_without_claiming_success(monkeypatch):
    import httpx
    evidence = {'evidence_id': 'source-1', 'evidence_type': 'source', 'excerpt': 'source'}
    provider = setup_provider(monkeypatch, [
        [{'type': 'function_call', 'name': 'read_source', 'call_id': '1', 'arguments': '{"file_path":"a.py"}'}],
    ])
    original = provider.post
    def post(*args, **kwargs):
        if provider.requests:
            raise httpx.ReadTimeout('secret provider details')
        return original(*args, **kwargs)
    provider.post = post
    monkeypatch.setattr(planner, 'dispatch', lambda *args: evidence)
    result = planner.run('repo-a', 'why?', None, [], [])
    assert result['answer'] is None
    assert result['execution']['status'] == 'failed'
    assert result['execution']['steps'][0]['status'] == 'completed'
    assert 'secret provider details' not in json.dumps(result)
