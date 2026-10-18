from backend.ingestion.github import GitHub


def test_recent_fix_selection_samples_all_keywords_before_global_bound():
    api = object.__new__(GitHub)
    api.repo = 'owner/repo'
    requests = []
    def get(route, params):
        requests.append(params)
        if 'fixes in:body' in params['q']:
            return {'items': [{'number': 1, 'body': 'fixes #1', 'created_at': '2020', 'updated_at': '2020'}]}
        if 'closes in:body' in params['q']:
            return {'items': [{'number': 2, 'body': 'closes #2', 'created_at': '2021', 'updated_at': '2026'}]}
        return {'items': []}
    api.get = get
    assert [pr['number'] for pr in api.fix_prs(limit=1, recent=True)] == [2]
    assert len(requests) == 3
    assert all(p['sort'] == 'updated' and p['order'] == 'desc' for p in requests)
    requests.clear()
    assert [pr['number'] for pr in api.fix_prs(limit=1)] == [1]
    assert requests[0]['sort'] == 'created' and requests[0]['order'] == 'asc'


def test_refresh_reports_rate_limit_instead_of_silently_returning_cached_data(tmp_path):
    import httpx
    import pytest
    api = object.__new__(GitHub)
    api.repo, api.cache, api.refresh = 'owner/repo', tmp_path, False
    state = {'limited': False}
    def transport(request):
        return httpx.Response(403, json={'message': 'API rate limit exceeded'}) if state['limited'] else httpx.Response(200, json={'items': [{'number': 1}]})
    with httpx.Client(base_url='https://api.github.com', transport=httpx.MockTransport(transport)) as client:
        api.client = client
        assert api.get('/search/issues')['items']
        state['limited'] = True
        assert api.get('/search/issues')['items']  # ordinary cached read
        api.refresh = True
        with pytest.raises(httpx.HTTPStatusError) as failure:
            api.get('/search/issues')
        assert failure.value.response.status_code == 403
