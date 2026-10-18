"""Git + actual FalkorDB fixtures; GitHub and provider networking are disabled."""
import os
import subprocess
import uuid
from pathlib import Path

import pytest

from backend import repositories as registry
from backend.agent.investigation import investigate, search_code, read_source
from backend.agent.evidence import validate_evidence
from backend.graph.client import Graph
from backend.ingestion.code_parser import parse_sources, persist
from backend.ingestion.git_history import ingest_history

pytestmark = [pytest.mark.integration, pytest.mark.skipif(os.getenv('WHYGRAPH_INTEGRATION') != '1', reason='requires FalkorDB')]


def git(path, *args, date=None):
    env = {**os.environ, 'GIT_AUTHOR_NAME': 'Fixture', 'GIT_COMMITTER_NAME': 'Fixture', 'GIT_AUTHOR_EMAIL': 'test@example.com', 'GIT_COMMITTER_EMAIL': 'test@example.com'}
    if date:
        env.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    return subprocess.run(['git', '-C', str(path), *args], env=env, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def indexed(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, 'DATA', tmp_path)
    monkeypatch.setattr(registry, 'REGISTRY', tmp_path / 'repositories.json')
    monkeypatch.delenv('LLM_API_KEY', raising=False)
    graphs, records = [], []
    for identity in ('fixture/alpha', 'fixture/beta'):
        record, _ = registry.register(identity)
        path = Path(record['checkout']); path.mkdir(parents=True)
        git(path, 'init', '-b', 'main')
        # Top-level side effect must not execute during ingestion.
        (path / 'engine.py').write_text('raise RuntimeError("NEVER EXECUTE REPOSITORY CODE")\ndef retry_request():\n    """Retry network requests with backoff."""\n    return 1\ndef caller():\n    return retry_request()\n')
        git(path, 'add', '.');git(path, 'commit', '-m', 'initial retry implementation', date='2020-01-01T00:00:00Z')
        (path / 'engine.py').write_text((path / 'engine.py').read_text().replace('return 1', 'return 2'))
        git(path, 'commit', '-am', 'fix network backoff', date='2021-01-01T00:00:00Z')
        ref = git(path, 'rev-parse', 'HEAD')
        g = Graph('whygraph_fixture_' + uuid.uuid4().hex);g.initialize();graphs.append(g)
        g.nodes('Repository', [{'id': identity, 'indexed_ref': ref}])
        ingest_history(g, identity, path, ref)
        persist(g, parse_sources(identity, {'engine.py': (path / 'engine.py').read_text()}, ref), identity, ref)
        registry.update(record['repository_id'], indexed_ref=ref, graph_name=g.name, status='ready')
        records.append(registry.get_repository(record['repository_id']))
    yield records
    for g in graphs:
        g.graph.delete()


def test_source_only_investigation_and_conversation_are_repository_isolated(indexed):
    a, b = indexed
    result = investigate(a['repository_id'], 'Where is network retry implemented?')
    assert result['mode'] == 'retrieval_only'
    assert result['findings']
    assert not result['historical_matches']
    assert all(e['repository_id'] == a['repository_id'] for e in result['evidence'])
    assert all('fixture/alpha' in e['source_url'] for e in result['evidence'])
    follow = investigate(a['repository_id'], 'What calls it and why was it changed?', result['conversation_id'])
    assert any(f['structure']['callers'] for f in follow['findings'])
    assert follow['conversation_id'] == result['conversation_id']
    with pytest.raises(ValueError, match='different repository'):
        investigate(b['repository_id'], 'what calls it?', result['conversation_id'])
    other = investigate(b['repository_id'], 'network retry')
    assert all('fixture/beta' in e['source_url'] for e in other['evidence'])


def test_dirty_checkout_and_forged_citations_cannot_change_verified_source(indexed):
    record = indexed[0]
    (Path(record['checkout']) / 'engine.py').write_text('def unrelated(): pass\n')
    result = search_code(record['repository_id'], 'network retry')
    assert result['results']
    assert any('return 2' in e['excerpt'] for e in result['results'])
    good = result['results'][0]
    forged = [{**good, 'repository_id': 'other'}, {**good, 'excerpt': 'invented source'}, {**good, 'start_line': 5000}, {**good, 'commit_sha': 'f'*40}]
    valid, rejected = validate_evidence([good] + forged, registry.context(record['repository_id']), result['revision'])
    assert valid == [good]
    assert len(rejected) == 4


def test_explicit_historical_source_excludes_later_content(indexed):
    record = indexed[0]
    result = search_code(record['repository_id'], 'network retry', as_of='2020-06-01T00:00:00Z')
    assert result['revision'] != record['indexed_ref']
    assert any('return 1' in e['excerpt'] for e in result['results'])
    assert all('return 2' not in e['excerpt'] for e in result['results'])
    with pytest.raises(ValueError):
        read_source(record['repository_id'], '../outside.py')


def test_refresh_fetches_upstream_revision_and_reindexes_source(indexed, monkeypatch):
    record = indexed[0]
    path = Path(record['checkout'])
    old_ref = record['indexed_ref']
    (path / 'engine.py').write_text('def authenticate_token():\n    """Authenticate credentials."""\n    return True\n')
    git(path, 'commit', '-am', 'introduce token authentication', date='2022-01-01T00:00:00Z')
    upstream_ref = git(path, 'rev-parse', 'HEAD')
    git(path, 'remote', 'add', 'origin', record['url'] + '.git')
    git(path, 'update-ref', 'refs/remotes/origin/main', upstream_ref)
    git(path, 'symbolic-ref', 'refs/remotes/origin/HEAD', 'refs/remotes/origin/main')
    git(path, 'reset', '--hard', old_ref)
    real_run, fetched = subprocess.run, []
    def run(arguments, **kwargs):
        if arguments[:4] == ['git', '-C', str(path), 'fetch']:
            fetched.append(arguments)
            return subprocess.CompletedProcess(arguments, 0, '', '')
        return real_run(arguments, **kwargs)
    monkeypatch.setattr(subprocess, 'run', run)
    monkeypatch.setattr('backend.ingestion.github.ingest_github', lambda *a, **k: [])
    monkeypatch.setattr('backend.graph.vectors.index_embeddings', lambda *a, **k: 0)
    job_id = 'fixture-refresh'
    registry._jobs[job_id] = {'job_id': job_id, 'repository_id': record['repository_id'], 'status': 'queued', 'stage': 'queued'}
    registry._ingest(record['repository_id'], job_id, True)
    updated = registry.get_repository(record['repository_id'])
    assert fetched
    assert updated['status'] == 'ready'
    assert updated['indexed_ref'] == upstream_ref
    result = search_code(record['repository_id'], 'token authentication')
    assert any(e['symbol']['name'] == 'authenticate_token' for e in result['results'])
    assert all(e['commit_sha'] == upstream_ref for e in result['results'])
    assert not search_code(record['repository_id'], 'network retry')['results']


def test_shared_pr_rationale_is_not_attributed_to_unrelated_symbol(indexed):
    from backend.graph.client import edge
    from backend.tools.history import history
    record = indexed[0]
    graph = Graph(record['graph_name'])
    symbol_id = record['identity'] + ':engine.py:engine.retry_request'
    at = '2021-01-01T00:00:00Z'
    span = 'Use exponential retry because the server may be temporarily unavailable.'
    source_url = record['url'] + '/pull/1'
    graph.nodes('PullRequest', [{'id': 'fixture-pr', 'number': 1, 'created_at': at, 'merged_at': at, 'updated_at': at, 'url': source_url, 'body': span}])
    graph.edges('PullRequest', 'CONTAINS_COMMIT', 'Commit', [edge('fixture-pr', record['indexed_ref'], 'fixture', timestamp=at)])
    graph.nodes('Claim', [{'id': 'fixture-claim', 'text': span, 'source_span': span, 'source_url': source_url, 'source_timestamp': at, 'created_at': at, 'valid_from': at}])
    graph.edges('Claim', 'EXPLAINS', 'PullRequest', [edge('fixture-claim', 'fixture-pr', 'fixture')])
    graph.edges('Claim', 'SUPPORTED_BY', 'PullRequest', [edge('fixture-claim', 'fixture-pr', 'fixture')])
    assert history(graph, symbol_id)['claims'] == []
    graph.edges('Claim', 'EXPLAINS', 'Symbol', [edge('fixture-claim', symbol_id, 'fixture')])
    result = history(graph, symbol_id)
    assert result['claims'][0]['source_span'] == span
    assert result['evidence'][0]['excerpt'] == span
    graph.query("MATCH (p:PullRequest {id:'fixture-pr'}) SET p.body='unrelated edited text'")
    assert history(graph, symbol_id)['claims'] == []


def test_search_ranks_beyond_5000_symbols_without_returning_file_text(indexed, monkeypatch):
    import json
    from backend.agent import investigation
    record = indexed[0]
    path = Path(record['checkout'])
    # One file with >5,000 symbols reproduces the former pre-ranking cutoff and
    # full-file-per-symbol transfer. Put the unique match after all 5,001 decoys
    # and beyond the target function's 1,200-character summary.
    source = ''.join(f'def decoy_{n:05d}():\n    return {n}\n' for n in range(5001))
    source += 'def z_final_target():\n' + '    # padding for full body search\n' * 60 + '    return "ultrarareheartbeatmarker"\n'
    (path / 'large.py').write_text(source)
    git(path, 'add', '.');git(path, 'commit', '-m', 'add large module', date='2022-01-01T00:00:00Z')
    ref = git(path, 'rev-parse', 'HEAD')
    graph = Graph(record['graph_name'])
    graph.nodes('Repository', [{'id': record['identity'], 'indexed_ref': ref}])
    persist(graph, parse_sources(record['identity'], {'large.py': source}, ref), record['identity'], ref)
    registry.update(record['repository_id'], indexed_ref=ref)
    real_query, transfers = Graph.query, []
    def query(self, cypher, params=None):
        rows = real_query(self, cypher, params)
        if 'AS ranking_score' in cypher:
            transfers.append((cypher, rows))
        return rows
    monkeypatch.setattr(Graph, 'query', query)
    reads, real_read = [], investigation.read_revision
    def read(*args):
        reads.append(args[2]);return real_read(*args)
    monkeypatch.setattr(investigation, 'read_revision', read)
    found = search_code(record['repository_id'], 'ultrarareheartbeatmarker', limit=2)
    assert found['results'][0]['symbol']['name'] == 'z_final_target'
    assert found['results'][0]['commit_sha'] == ref
    assert len(transfers[0][1]) <= 6
    assert 'source_text' not in transfers[0][0]
    assert len(json.dumps(transfers[0][1])) < 2000
    assert reads == ['large.py']
    # Historical searches must use the older per-snapshot text, not this file.
    assert not search_code(record['repository_id'], 'ultrarareheartbeatmarker', as_of='2021-06-01T00:00:00Z')['results']


def test_legacy_snapshot_search_fields_upgrade_without_mutating_source(indexed):
    record = indexed[0]
    graph = Graph(record['graph_name'])
    graph.query('MATCH ()-[e:CONTAINS]->() WHERE e.snapshot_ref=$ref REMOVE e.search_text,e.search_metadata_json,e.search_names,e.search_kind', {'ref': record['indexed_ref']})
    (Path(record['checkout']) / 'engine.py').write_text('def unrelated(): pass\n')
    result = search_code(record['repository_id'], 'network retry')
    assert result['results']
    assert any('return 2' in item['excerpt'] for item in result['results'])
    assert graph.query('MATCH ()-[e:CONTAINS]->() WHERE e.snapshot_ref=$ref AND e.search_text IS NULL RETURN count(e)', {'ref': record['indexed_ref']}) == [[0]]


def test_refresh_bypasses_cached_github_search_and_records_new_fix(indexed, monkeypatch, tmp_path):
    import httpx
    from backend.ingestion import github
    record = indexed[0]
    path = Path(record['checkout'])
    graph = Graph(record['graph_name'])
    old_ref = record['indexed_ref']
    state, reads = {'new': False}, []
    def issue(number, pull=False):
        at = '2022-01-01T00:00:00Z' if number == 2 else '2021-01-01T00:00:00Z'
        result = {'id': number, 'number': number, 'title': f'fix {number}', 'body': f'Fixes #{number}', 'created_at': at, 'updated_at': at, 'state': 'closed', 'html_url': record['url'] + ('/pull/' if pull else '/issues/') + str(number), 'user': {'login': 'fixture'}}
        if pull: result['pull_request'] = {'merged_at': at}
        return result
    def transport(request):
        reads.append(str(request.url))
        route = request.url.path
        if route == '/search/issues':
            values = ([issue(2, True)] if state['new'] else []) + [issue(1, True)]
            return httpx.Response(200, json={'items': values if 'fixes in:body' in request.url.params['q'] else []})
        if '/pulls/' in route and route.endswith('/commits'):
            number = int(route.split('/')[-2])
            return httpx.Response(200, json=[{'sha': upstream_ref if number == 2 else old_ref, 'author': None}])
        if '/issues/' in route:
            return httpx.Response(200, json=issue(int(route.rsplit('/', 1)[-1])))
        raise AssertionError('Unexpected GitHub read ' + str(request.url))
    original = github.GitHub
    class FixtureGitHub(original):
        def __init__(self, repo=None, refresh=False):
            super().__init__(repo, refresh)
            self.client.close()
            self.client = httpx.Client(base_url='https://api.github.com', transport=httpx.MockTransport(transport))
            self.cache = tmp_path / 'github-cache';self.cache.mkdir(exist_ok=True)
    monkeypatch.setattr(github, 'GitHub', FixtureGitHub)
    github.ingest_github(graph, record['identity'], checkout=path, recent=True)
    assert graph.query('MATCH (p:PullRequest) RETURN count(p)') == [[1]]
    # A new fix appears after the search, issue and commit responses were cached.
    (path / 'engine.py').write_text('def authenticate_token():\n    return True\n')
    git(path, 'commit', '-am', 'new authentication fix', date='2022-01-01T00:00:00Z')
    upstream_ref = git(path, 'rev-parse', 'HEAD')
    git(path, 'remote', 'add', 'origin', record['url'] + '.git')
    git(path, 'update-ref', 'refs/remotes/origin/main', upstream_ref)
    git(path, 'symbolic-ref', 'refs/remotes/origin/HEAD', 'refs/remotes/origin/main')
    git(path, 'reset', '--hard', old_ref)
    real_run = subprocess.run
    def run(arguments, **kwargs):
        if arguments[:4] == ['git', '-C', str(path), 'fetch']:
            return subprocess.CompletedProcess(arguments, 0, '', '')
        return real_run(arguments, **kwargs)
    monkeypatch.setattr(subprocess, 'run', run)
    monkeypatch.setattr('backend.graph.vectors.index_embeddings', lambda *a, **k: 0)
    state['new'] = True;reads.clear()
    job_id = 'fixture-new-github-fix'
    registry._jobs[job_id] = {'job_id': job_id, 'repository_id': record['repository_id'], 'status': 'queued', 'stage': 'queued'}
    registry._ingest(record['repository_id'], job_id, True)
    assert registry.get_job(job_id)['status'] == 'completed'
    updated = registry.get_repository(record['repository_id'])
    assert updated['status'] == 'ready'
    assert updated['counts']['Symbol'] == 1
    assert updated['graph_counts']['Symbol'] > updated['counts']['Symbol']
    from backend.api import routes
    monkeypatch.setattr(routes, 'graph', lambda: graph)
    status = routes.status()
    assert status['counts']['Symbol'] == status['current_symbols'] == 1
    assert status['graph_counts']['Symbol'] > 1
    links = graph.query('MATCH (p:PullRequest)-[:CLOSES]->(i:Issue), (p)-[:CONTAINS_COMMIT]->(c:Commit) WHERE p.number=2 RETURN i.number,c.sha')
    assert links == [[2, upstream_ref]]
    assert any('/search/issues?' in url for url in reads)
    assert any('/pulls/1/commits' in url for url in reads)
    assert any('/issues/1' in url for url in reads)
