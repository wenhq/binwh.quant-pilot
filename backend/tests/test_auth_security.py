import pytest

from app.services.auth.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_hash_and_verify_password():
    hashed = hash_password("secret")
    assert hashed != "secret"
    assert verify_password("secret", hashed) is True
    assert verify_password("wrong", hashed) is False


def test_create_and_decode_access_token():
    token = create_access_token("alice")
    payload = decode_token(token)
    assert payload["sub"] == "alice"
    assert "exp" in payload


def test_create_and_decode_refresh_token():
    token = create_refresh_token("alice")
    payload = decode_token(token)
    assert payload["sub"] == "alice"


def test_decode_invalid_token_raises():
    with pytest.raises(ValueError):
        decode_token("not-a-real-token")
