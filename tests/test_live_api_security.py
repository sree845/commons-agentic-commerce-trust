import pytest
from fastapi import HTTPException

from src.api import _require_operator, _require_reviewer


def test_operator_actions_fail_closed_without_token(monkeypatch):
    monkeypatch.delenv("COMMONS_OPERATOR_TOKEN", raising=False)
    with pytest.raises(HTTPException) as error:
        _require_operator("Bearer anything")
    assert error.value.status_code == 503


def test_operator_token_is_required(monkeypatch):
    monkeypatch.setenv("COMMONS_OPERATOR_TOKEN", "test-operator-secret")
    with pytest.raises(HTTPException) as error:
        _require_operator("Bearer wrong")
    assert error.value.status_code == 401
    _require_operator("Bearer test-operator-secret")


def test_reviewer_token_is_required(monkeypatch):
    monkeypatch.setenv("COMMONS_REVIEWER_TOKEN", "test-reviewer-secret")
    with pytest.raises(HTTPException) as error:
        _require_reviewer(None)
    assert error.value.status_code == 401
    _require_reviewer("Bearer test-reviewer-secret")
