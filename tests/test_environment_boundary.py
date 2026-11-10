"""Production boundary must not depend on APP_ENV casing or whitespace."""
import pytest
from fastapi import HTTPException, Response
from aadharshila.runtime import is_production
from aadharshila.main import Login, login
from aadharshila.risk_serving import ResearchModelUnavailable, load_pinned_research_model


@pytest.mark.parametrize('mode', ['production', 'PRODUCTION', ' ProDuCtIoN ', 'staging', 'prod'])
def test_restricted_environment_disables_local_login_and_research(monkeypatch, mode):
    monkeypatch.setenv('APP_ENV', mode)
    assert is_production()
    with pytest.raises(HTTPException) as caught:
        login(Login(username='analyst', password='Demo@12345'), Response(), db=None)
    assert caught.value.status_code == 403
    with pytest.raises(ResearchModelUnavailable, match='disabled in production'):
        load_pinned_research_model()


@pytest.mark.parametrize('mode', ['development', ' DEVELOPMENT ', 'test'])
def test_explicit_local_environment(monkeypatch, mode):
    monkeypatch.setenv('APP_ENV', mode)
    assert not is_production()
