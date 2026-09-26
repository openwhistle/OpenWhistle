"""Tests for OIDC service and endpoints."""

import base64
import hashlib
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import AsyncClient
from jwt.algorithms import RSAAlgorithm
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services import oidc as oidc_service
from app.services.auth import get_user_by_oidc_sub

_FAKE_METADATA = {
    "issuer": "https://idp.example.com",
    "authorization_endpoint": "https://idp.example.com/auth",
    "token_endpoint": "https://idp.example.com/token",
    "userinfo_endpoint": "https://idp.example.com/userinfo",
    "jwks_uri": "https://idp.example.com/jwks",
}


# ── Endpoint tests (OIDC disabled in test env) ────────────────────────────────


@pytest.mark.asyncio
async def test_oidc_authorize_returns_404_when_disabled(client: AsyncClient) -> None:
    response = await client.get("/admin/oidc/authorize", follow_redirects=False)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_oidc_callback_returns_404_when_disabled(client: AsyncClient) -> None:
    response = await client.get("/admin/oidc/callback?code=x&state=y", follow_redirects=False)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_oidc_callback_no_params_when_disabled(client: AsyncClient) -> None:
    response = await client.get("/admin/oidc/callback", follow_redirects=False)
    assert response.status_code == 404


# ── Service unit tests ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_user_by_oidc_sub_not_found(db_session: AsyncSession) -> None:
    result = await get_user_by_oidc_sub(db_session, "nonexistent-sub", "https://idp.example.com")
    assert result is None


@pytest.mark.asyncio
async def test_oidc_exchange_code_invalid_state() -> None:
    """exchange_code returns None when state key is not in Redis."""
    mock_redis = AsyncMock()
    mock_redis.getdel = AsyncMock(return_value=None)

    result = await oidc_service.exchange_code(mock_redis, "some-code", "invalid-state")

    assert result is None
    mock_redis.getdel.assert_called_once()


@pytest.mark.asyncio
async def test_oidc_create_authorization_url_format() -> None:
    """create_authorization_url returns a URL with required OAuth parameters."""
    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=True)

    with patch("app.services.oidc._get_metadata", new=AsyncMock(return_value=_FAKE_METADATA)):
        url = await oidc_service.create_authorization_url(mock_redis)

    assert url.startswith("https://idp.example.com/auth?")
    assert "response_type=code" in url
    assert "scope=openid" in url
    assert "state=" in url
    assert "nonce=" in url
    mock_redis.set.assert_called_once()


@pytest.mark.asyncio
async def test_oidc_get_metadata_calls_correct_url() -> None:
    """_get_metadata fetches the OIDC well-known endpoint."""
    fake_resp = MagicMock()
    fake_resp.raise_for_status = MagicMock()
    fake_resp.json = MagicMock(return_value=_FAKE_METADATA)

    mock_http_client = AsyncMock()
    mock_http_client.get = AsyncMock(return_value=fake_resp)
    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_http_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_http_client):
        result = await oidc_service._get_metadata()  # noqa: SLF001

    assert result["issuer"] == "https://idp.example.com"


# ── ID token verification, PKCE, nonce (locally generated RSA key) ───────────

_CLIENT_ID = "openwhistle-client"
_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_JWK = {**json.loads(RSAAlgorithm.to_jwk(_KEY.public_key())), "kid": "k1", "alg": "RS256"}


def _id_token(key: object = _KEY, alg: str = "RS256", **overrides: object) -> str:
    now = int(time.time())
    claims: dict[str, object] = {
        "iss": _FAKE_METADATA["issuer"],
        "sub": "user-123",
        "aud": _CLIENT_ID,
        "iat": now,
        "exp": now + 300,
        "nonce": "the-nonce",
    }
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm=alg, headers={"kid": "k1"})  # type: ignore[arg-type]


class _FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.data[key] = value

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def getdel(self, key: str) -> str | None:
        return self.data.pop(key, None)


def _stored_state(redis: _FakeRedis, state: str = "the-state") -> None:
    redis.data[f"openwhistle:oidc_state:{state}"] = json.dumps(
        {"nonce": "the-nonce", "code_verifier": "the-verifier"}
    )


async def _exchange(
    redis: _FakeRedis, token_response: dict[str, object], state: str = "the-state"
) -> tuple[dict[str, object] | None, AsyncMock]:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=token_response)
    http = AsyncMock()
    http.post = AsyncMock(return_value=resp)
    http.__aenter__ = AsyncMock(return_value=http)
    http.__aexit__ = AsyncMock(return_value=None)
    with patch("app.services.oidc._get_metadata", new=AsyncMock(return_value=_FAKE_METADATA)), \
         patch("httpx.AsyncClient", return_value=http), \
         patch.object(jwt.PyJWKClient, "fetch_data", return_value={"keys": [_JWK]}):
        result = await oidc_service.exchange_code(redis, "auth-code", state)  # type: ignore[arg-type]
    return result, http


@pytest.fixture(autouse=True)
def _client_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "oidc_client_id", _CLIENT_ID)


@pytest.mark.asyncio
async def test_authorization_url_carries_pkce_s256_and_nonce() -> None:
    redis = _FakeRedis()
    with patch("app.services.oidc._get_metadata", new=AsyncMock(return_value=_FAKE_METADATA)):
        url = await oidc_service.create_authorization_url(redis)  # type: ignore[arg-type]

    query = parse_qs(urlsplit(url).query)
    (stored,) = redis.data.values()
    stored_state = json.loads(stored)
    digest = hashlib.sha256(stored_state["code_verifier"].encode()).digest()
    assert query["code_challenge"] == [base64.urlsafe_b64encode(digest).rstrip(b"=").decode()]
    assert query["code_challenge_method"] == ["S256"]
    assert query["nonce"] == [stored_state["nonce"]]


@pytest.mark.asyncio
async def test_valid_id_token_yields_identity_and_code_verifier_is_sent() -> None:
    redis = _FakeRedis()
    _stored_state(redis)

    claims, http = await _exchange(redis, {"access_token": "a", "id_token": _id_token()})

    assert claims is not None
    assert claims["sub"] == "user-123"
    assert claims["iss"] == _FAKE_METADATA["issuer"]
    assert http.post.call_args.kwargs["data"]["code_verifier"] == "the-verifier"


@pytest.mark.asyncio
async def test_state_is_single_use() -> None:
    redis = _FakeRedis()
    _stored_state(redis)
    token = {"access_token": "a", "id_token": _id_token()}

    assert (await _exchange(redis, token))[0] is not None
    assert (await _exchange(redis, token))[0] is None


@pytest.mark.parametrize(
    ("label", "token_kwargs"),
    [
        ("wrong nonce", {"nonce": "someone-elses-nonce"}),
        ("no nonce", {"nonce": None}),
        ("wrong audience", {"aud": "another-client"}),
        ("wrong issuer", {"iss": "https://evil.example.com"}),
        ("expired", {"exp": int(time.time()) - 3600, "iat": int(time.time()) - 7200}),
        ("foreign key", {"key": _OTHER_KEY}),
        ("symmetric alg", {"key": "shared-secret-shared-secret-shared", "alg": "HS256"}),
        ("several audiences, no azp", {"aud": [_CLIENT_ID, "other"]}),
    ],
)
@pytest.mark.asyncio
async def test_id_token_that_does_not_verify_is_refused(
    label: str, token_kwargs: dict[str, object]
) -> None:
    redis = _FakeRedis()
    _stored_state(redis)
    claims, _ = await _exchange(redis, {"access_token": "a", "id_token": _id_token(**token_kwargs)})
    assert claims is None, label


@pytest.mark.asyncio
async def test_several_audiences_with_matching_azp_is_accepted() -> None:
    redis = _FakeRedis()
    _stored_state(redis)
    token = _id_token(aud=[_CLIENT_ID, "other"], azp=_CLIENT_ID)
    claims, _ = await _exchange(redis, {"access_token": "a", "id_token": token})
    assert claims is not None


@pytest.mark.asyncio
async def test_token_response_without_id_token_is_refused() -> None:
    redis = _FakeRedis()
    _stored_state(redis)
    claims, _ = await _exchange(redis, {"access_token": "a"})
    assert claims is None
