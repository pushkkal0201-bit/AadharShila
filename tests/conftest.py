import os, tempfile
from pathlib import Path
import pytest

# Initialize the app against an isolated disposable database for the entire suite.
TEST_DIR=Path(tempfile.mkdtemp(prefix='aadharshila-tests-'))
os.environ['DATABASE_URL']='sqlite:///'+str(TEST_DIR/'test.db')
os.environ['UPLOAD_DIR']=str(TEST_DIR/'documents')
os.environ['SEED_DEMO']='true'
os.environ['APP_ENV']='development'

from fastapi.testclient import TestClient
from aadharshila.main import app

@pytest.fixture(scope='session')
def client():
    with TestClient(app) as c:yield c

@pytest.fixture
def login(client):
    def login_as(name='analyst'):
        r=client.post('/api/v1/auth/login',json={'username':name,'password':'Demo@12345'})
        assert r.status_code==200,r.text
        return {'X-CSRF-Token':r.json()['csrf']}
    return login_as

@pytest.fixture
def cases(client,login):
    login('analyst')
    r=client.get('/api/v1/applications')
    assert r.status_code==200
    return {a['reference']:a for a in r.json()['items']}
