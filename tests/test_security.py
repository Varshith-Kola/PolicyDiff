"""Security-focused tests for PolicyDiff.

Tests URL validation (SSRF prevention), API key verification,
bearer token generation/verification, and input sanitization.
"""

import pytest
from app.utils.url_validator import validate_policy_url
from app.utils.security import (
    generate_api_key,
    hash_api_key,
    verify_api_key,
    generate_bearer_token,
    verify_bearer_token,
)


class TestURLValidator:
    """SSRF prevention tests."""

    def test_valid_https_url(self):
        ok, err = validate_policy_url("https://example.com/privacy")
        assert ok is True
        assert err is None

    def test_valid_http_url(self):
        ok, err = validate_policy_url("http://example.com/privacy")
        assert ok is True
        assert err is None

    def test_reject_ftp_scheme(self):
        ok, err = validate_policy_url("ftp://example.com/file")
        assert ok is False
        assert "scheme" in err.lower()

    def test_reject_javascript_scheme(self):
        ok, err = validate_policy_url("javascript:alert(1)")
        assert ok is False

    def test_reject_empty_url(self):
        ok, err = validate_policy_url("")
        assert ok is False

    def test_reject_localhost(self):
        ok, err = validate_policy_url("http://localhost/admin")
        assert ok is False
        assert "not allowed" in err.lower()

    def test_reject_private_ip_10(self):
        ok, err = validate_policy_url("http://10.0.0.1/secret")
        assert ok is False
        assert "private" in err.lower()

    def test_reject_private_ip_192(self):
        ok, err = validate_policy_url("http://192.168.1.1/admin")
        assert ok is False

    def test_reject_private_ip_172(self):
        ok, err = validate_policy_url("http://172.16.0.1/internal")
        assert ok is False

    def test_reject_loopback(self):
        ok, err = validate_policy_url("http://127.0.0.1/")
        assert ok is False

    def test_reject_metadata_endpoint(self):
        ok, err = validate_policy_url("http://metadata.google.internal/computeMetadata/v1/")
        assert ok is False

    def test_reject_too_long_url(self):
        ok, err = validate_policy_url("https://example.com/" + "a" * 2100)
        assert ok is False
        assert "length" in err.lower()


class TestAPIKeySecurity:
    def test_generate_key_format(self):
        key = generate_api_key()
        assert key.startswith("pd_")
        assert len(key) > 30

    def test_hash_and_verify(self):
        key = generate_api_key()
        hashed = hash_api_key(key)
        assert verify_api_key(key, hashed) is True
        assert verify_api_key("wrong_key", hashed) is False

    def test_hash_is_deterministic(self):
        key = "test_key_123"
        assert hash_api_key(key) == hash_api_key(key)


class TestBearerToken:
    def test_generate_and_verify(self):
        secret = "test_secret_key"
        token = generate_bearer_token(user_id=42, secret=secret, expires_hours=1)
        user_id = verify_bearer_token(token, secret)
        assert user_id == 42

    def test_wrong_secret_fails(self):
        token = generate_bearer_token(user_id=1, secret="secret1")
        assert verify_bearer_token(token, "secret2") is None

    def test_expired_token_fails(self):
        token = generate_bearer_token(user_id=1, secret="s", expires_hours=-1)
        assert verify_bearer_token(token, "s") is None

    def test_malformed_token_fails(self):
        assert verify_bearer_token("not:a:valid:token", "s") is None
        assert verify_bearer_token("", "s") is None
        assert verify_bearer_token("abc", "s") is None
