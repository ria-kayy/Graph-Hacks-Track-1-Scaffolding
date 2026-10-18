import json
import threading
from concurrent.futures import Future, ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from backend import repositories as registry
from backend.main import app


@pytest.fixture
def registry_store(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, 'DATA', tmp_path)
    monkeypatch.setattr(registry, 'REGISTRY', tmp_path / 'repositories.json')
    monkeypatch.setattr(registry, '_jobs', {})
    monkeypatch.setattr(registry, '_slots', threading.BoundedSemaphore(8))
    return registry


class DeferredPool:
    def __init__(self):
        self.submitted = []

    def submit(self, *args):
        self.submitted.append(args)
        return Future()


def test_concurrent_registration_and_start_are_idempotent(registry_store, monkeypatch):
    pool = DeferredPool()
    monkeypatch.setattr(registry, '_pool', pool)
    def start(_):
        record, _ = registry.register('Owner/Repo')
        return registry.start_ingestion(record['repository_id'])['job_id']
    with ThreadPoolExecutor(max_workers=8) as executor:
        jobs = list(executor.map(start, range(16)))
    assert len(set(jobs)) == 1
    assert len(pool.submitted) == 1
    assert len(registry._read()) == 1


def test_restart_exposes_interrupted_job_and_retry(registry_store, monkeypatch):
    pool = DeferredPool()
    monkeypatch.setattr(registry, '_pool', pool)
    record, _ = registry.register('owner/repo')
    job = registry.start_ingestion(record['repository_id'])
    registry._jobs.clear()  # simulate a new backend process
    assert registry.get_job(job['job_id'])['status'] == 'failed'
    assert 'restart' in registry.get_repository(record['repository_id'])['error']
    retried = registry.start_ingestion(record['repository_id'], refresh=True)
    assert retried['job_id'] != job['job_id']


def test_job_queue_is_bounded(registry_store, monkeypatch):
    monkeypatch.setattr(registry, '_pool', DeferredPool())
    for n in range(8):
        record, _ = registry.register(f'owner/repo{n}')
        registry.start_ingestion(record['repository_id'])
    record, _ = registry.register('owner/overflow')
    with pytest.raises(ValueError, match='queue is full'):
        registry.start_ingestion(record['repository_id'])


def test_clone_failure_is_visible_and_never_ready(registry_store, monkeypatch):
    record, _ = registry.register('owner/repo')
    job_id = 'failed-clone'
    registry._jobs[job_id] = {'job_id': job_id, 'status': 'queued', 'stage': 'queued'}
    def fail(*args, **kwargs):
        raise RuntimeError('network unavailable')
    monkeypatch.setattr(registry.subprocess, 'run', fail)
    registry._ingest(record['repository_id'], job_id, False)
    assert registry.get_job(job_id)['status'] == 'failed'
    assert registry.get_repository(record['repository_id'])['status'] == 'failed'
    assert 'network unavailable' in registry.get_job(job_id)['error']


def test_admin_endpoints_are_disabled_for_remote_and_public_clients(registry_store, monkeypatch):
    remote = TestClient(app, client=('203.0.113.1', 12345))
    assert remote.post('/api/repositories', json={'repository': 'owner/repo'}).status_code == 403
    monkeypatch.setenv('WHYGRAPH_PUBLIC', 'true')
    local = TestClient(app, base_url='http://localhost', client=('127.0.0.1', 12345))
    assert local.post('/api/repositories', json={'repository': 'owner/repo'}).status_code == 403
    assert not registry._read()


def test_unknown_repository_and_bad_tool_arguments_return_client_errors():
    client = TestClient(app)
    assert client.post('/api/query', json={'tool': 'history', 'repo_id': 'unknown', 'symbol': 'retry'}).status_code == 404
    assert client.post('/api/tools', json={'repo_id': 'default', 'tool': 'shell', 'arguments': {'command': 'pwd'}}).status_code == 422


@pytest.mark.parametrize('headers,base_url', [
    ({}, 'https://whygraph.example'),
    ({'X-Forwarded-For': '203.0.113.1'}, 'http://localhost'),
    ({'Forwarded': 'for=203.0.113.1;proto=https'}, 'http://localhost'),
    ({'Origin': 'https://untrusted.example'}, 'http://localhost'),
])
def test_loopback_proxy_cannot_use_unauthenticated_admin(registry_store, monkeypatch, headers, base_url):
    monkeypatch.delenv('WHYGRAPH_ADMIN_TOKEN', raising=False)
    client = TestClient(app, base_url=base_url, client=('127.0.0.1', 50000))
    assert client.post('/api/repositories', json={'repository': 'owner/repo'}, headers=headers).status_code == 403
    assert not registry._read()


def test_configured_admin_token_is_required_even_on_loopback(registry_store, monkeypatch):
    from backend.api import routes
    monkeypatch.setenv('WHYGRAPH_ADMIN_TOKEN', 'fixture-admin-secret')
    monkeypatch.setattr(routes, 'start_ingestion', lambda *args, **kwargs: {'status': 'queued'})
    client = TestClient(app, base_url='https://whygraph.example', client=('127.0.0.1', 50000))
    for authorization in ('', 'Bearer wrong'):
        assert client.post('/api/repositories', json={'repository': 'owner/repo'}, headers={'Authorization': authorization}).status_code == 403
    response = client.post('/api/repositories', json={'repository': 'owner/repo'}, headers={'Authorization': 'Bearer fixture-admin-secret', 'X-Forwarded-For': '203.0.113.1'})
    assert response.status_code == 200
    monkeypatch.setenv('WHYGRAPH_PUBLIC', 'true')
    assert client.post('/api/repositories', json={'repository': 'owner/repo'}, headers={'Authorization': 'Bearer fixture-admin-secret'}).status_code == 403
