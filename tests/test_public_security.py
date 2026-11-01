"""Real service boundary probes with disposable identities/storage, no production load."""
import pytest
from test_service import service, login, upload


@pytest.mark.parametrize('suffix', ['', '?version=1', '/audit', '/documents/doc1',
                                  '/documents/doc1/page/1', '/search?q=principal',
                                  '/export?format=json', '/export?format=csv',
                                  '/findings/F1/draft?version=1&revision=0', '/ocr'])
def test_all_case_surfaces_keep_workspace_boundary(service, suffix):
    client, _, _ = service
    headers = login(client)
    report = upload(client, headers).json()
    path = '/api/cases/' + report['id'] + suffix
    client.cookies.clear()
    assert client.get(path).status_code == 401
    login(client, 'other@example.invalid')
    assert client.get(path).status_code == 404


def test_forwarded_headers_do_not_evade_local_login_budget(service):
    client, _, _ = service
    for index in range(10):
        response = client.post('/api/platform/auth/login',
                               json={'email': 'absent@example.invalid', 'password': 'synthetic-wrong-password'},
                               headers={'X-Forwarded-For': f'192.0.2.{index+1}'})
        assert response.status_code == 401
    response = client.post('/api/platform/auth/login',
                           json={'email': 'absent@example.invalid', 'password': 'synthetic-wrong-password'},
                           headers={'X-Forwarded-For': '198.51.100.1'})
    assert response.status_code == 429
    # This proves application handling, not Vercel's forwarding-chain behavior.


def test_forged_csrf_cross_origin_and_cookie_flags(service):
    client, _, _ = service
    response = client.post('/api/platform/demo/start')
    assert response.status_code == 200
    cookies = response.headers.get_list('set-cookie')
    assert any(c.startswith('pta_session=') and 'HttpOnly' in c and 'Secure' in c and 'SameSite=strict' in c for c in cookies)
    csrf = client.cookies['pta_csrf']
    assert client.post('/api/platform/demo/cases/clean', headers={'X-CSRF-Token': 'synthetic-forgery'}).status_code == 403
    assert client.post('/api/platform/demo/cases/clean', headers={'X-CSRF-Token': csrf, 'Origin': 'https://evil.invalid'}).status_code == 403
    assert client.get('/api/cases').json()['cases'] == []


@pytest.mark.parametrize('path', ['/.env', '/.env.production', '/.git/config', '/.git/HEAD',
                                '/storage/private/report.json', '/data/private/statement.pdf',
                                '/app/main.py', '/requirements-lock.txt'])
def test_private_files_not_web_routes(service, path):
    client, _, _ = service
    assert client.get(path).status_code == 404


def test_request_limit_precedes_analysis_and_paid_provider(service, monkeypatch):
    from app import main
    client, _, _ = service
    monkeypatch.setenv('VERCEL', '1')
    def forbidden(*args, **kwargs):
        raise AssertionError('Oversized unauthorized body must not reach provider or parser')
    monkeypatch.setattr(main.meta, 'request', forbidden)
    response = client.post('/api/analyze', content=b'x'*4_000_001)
    assert response.status_code == 413
    assert response.json()['detail'].startswith('Maximum total service request')


def test_session_tampering_cannot_become_authenticated(service):
    client, _, _ = service
    client.cookies.set('pta_session', 'demo.not-a-valid-encrypted-session')
    assert client.get('/api/platform/auth/me').status_code == 401
    assert client.get('/api/cases').status_code == 401
