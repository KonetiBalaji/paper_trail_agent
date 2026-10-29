from test_api import client,upload

def test_local_history_search_and_filters(client):
    a=upload(client,'clean').json();b=upload(client,'math_error').json()
    rows=client.get('/api/cases').json()['cases']
    assert {r['id'] for r in rows}=={a['id'],b['id']}
    assert client.get('/api/cases',params={'q':'DEMO-001','status':'consistent'}).json()['total_in_window']==1
    assert client.get('/api/cases',params={'q':'2026-10-31','status':'discrepancies'}).json()['total_in_window']==1
    client.patch(f"/api/cases/{b['id']}/findings/F1",json={'action':'confirm','expected_revision':0})
    assert client.get('/api/cases',params={'decision':'confirmed'}).json()['cases'][0]['id']==b['id']
    assert client.get('/api/cases',params={'q':'not-present'}).json()['cases']==[]

def test_history_pagination_and_invalid_filter(client):
    upload(client,'clean');upload(client,'math_error')
    assert len(client.get('/api/cases',params={'limit':1,'offset':1}).json()['cases'])==1
    assert client.get('/api/cases',params={'status':'fake'}).status_code==422
    assert client.get('/api/cases',params={'decision':'fake'}).status_code==422
    assert client.get('/api/cases',params={'limit':1000}).status_code==422
