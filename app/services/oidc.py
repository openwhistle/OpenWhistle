"""OIDC Authorization Code Flow (with PKCE) for admin single sign-on.

The identity (``sub`` + ``iss``) comes from the ID token, verified against the
provider's JWKS: signature, issuer, audience, expiry and the nonce this login
sent. A userinfo response alone is never trusted for identity.
"""

import asyncio
import base64
import hashlib
import json
import secrets
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from redis.asyncio import Redis

from app.config import settings

_STATE_PREFIX = "openwhistle:oidc_state:"
_STATE_TTL = 300  # 5 minutes

# A state is issued for one purpose and redeemed only for that purpose: a login
# state can never link an identity, a link state can never sign anybody in.
# The prefix on the state value only tells the callback which mode to expect;
# the purpose and session binding stored in Redis are what is checked.
PURPOSE_LOGIN = "login"
PURPOSE_LINK = "link"
LINK_STATE_PREFIX = "link."

# Outcomes of linking, shown on /admin/account after the redirect (?sso=…).
SSO_RESULTS = frozenset({"linked", "unlinked", "failed", "taken", "only_way_in"})

# Asymmetric algorithms only: the key must come from the provider's JWKS.
# HS* would turn the (shared) client secret into a signing key and "none"
# would disable the check entirely.
_ALLOWED_ALGORITHMS = [
    "RS256",
    "RS384",
    "RS512",
    "PS256",
    "PS384",
    "PS512",
    "ES256",
    "ES384",
    "ES512",
    "EdDSA",
]
_CLOCK_SKEW_SECONDS = 60


async def _get_metadata() -> dict[str, Any]:
    async with httpx.AsyncClient() as client:
        response = await client.get(settings.oidc_server_metadata_url, timeout=10)
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return data


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def session_binding(user_id: str, session_token: str) -> str:
    """What ties a link state to the admin session that started it.

    A hash, so Redis never holds a second copy of a live session token.
    """
    return hashlib.sha256(f"{user_id}:{session_token}".encode()).hexdigest()


async def create_authorization_url(
    redis: Redis, purpose: str = PURPOSE_LOGIN, binding: str = ""
) -> str:
    """Generate the OIDC authorization URL; store state, nonce and PKCE verifier.

    ``binding`` (from ``session_binding``) is required for a link state.
    """
    metadata = await _get_metadata()
    authorization_endpoint: str = metadata["authorization_endpoint"]

    state = secrets.token_urlsafe(32)
    if purpose == PURPOSE_LINK:
        state = LINK_STATE_PREFIX + state
    nonce = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)  # 86 chars, within RFC 7636's 43-128
    await redis.set(
        f"{_STATE_PREFIX}{state}",
        json.dumps(
            {
                "nonce": nonce,
                "code_verifier": code_verifier,
                "purpose": purpose,
                "binding": binding,
            }
        ),
        ex=_STATE_TTL,
    )

    params = {
        "response_type": "code",
        "client_id": settings.oidc_client_id,
        "redirect_uri": settings.oidc_redirect_uri,
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": _pkce_challenge(code_verifier),
        "code_challenge_method": "S256",
    }
    return f"{authorization_endpoint}?{urlencode(params)}"


def _verify_id_token(
    id_token: str, jwks_uri: str, issuer: str, nonce: str
) -> dict[str, Any] | None:
    """Verify the ID token and return its claims, or None if it does not hold.

    Sync: PyJWKClient fetches the JWKS with urllib. Run it in a thread.
    """
    try:
        signing_key = jwt.PyJWKClient(jwks_uri, timeout=10).get_signing_key_from_jwt(id_token)
        claims: dict[str, Any] = jwt.decode(
            id_token,
            signing_key,
            algorithms=_ALLOWED_ALGORITHMS,
            audience=settings.oidc_client_id,
            issuer=issuer,
            leeway=_CLOCK_SKEW_SECONDS,
            options={"require": ["iss", "sub", "aud", "exp", "iat", "nonce"]},
        )
    except jwt.PyJWTError:
        return None
    if not secrets.compare_digest(str(claims["nonce"]), nonce):
        return None
    # OIDC Core 3.1.3.7: with several audiences, azp must name this client.
    aud = claims["aud"]
    if isinstance(aud, list) and len(aud) > 1 and claims.get("azp") != settings.oidc_client_id:
        return None
    return claims


async def exchange_code(
    redis: Redis, code: str, state: str, purpose: str = PURPOSE_LOGIN, binding: str = ""
) -> dict[str, Any] | None:
    """Exchange the authorization code; return the verified ID token claims.

    None when the state is unknown or already used, was issued for another
    purpose or another session, or the ID token does not verify. State, nonce
    and PKCE verifier are single use (GETDEL), whatever the outcome.
    """
    raw = await redis.getdel(f"{_STATE_PREFIX}{state}")
    if not raw:
        return None
    stored: dict[str, str] = json.loads(raw)
    # States stored before v2.1.0 carry no purpose: they were login states.
    if stored.get("purpose", PURPOSE_LOGIN) != purpose:
        return None
    if not secrets.compare_digest(stored.get("binding", ""), binding):
        return None

    metadata = await _get_metadata()

    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            metadata["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.oidc_redirect_uri,
                "client_id": settings.oidc_client_id,
                "client_secret": settings.oidc_client_secret,
                "code_verifier": stored["code_verifier"],
            },
            timeout=10,
        )
        token_resp.raise_for_status()
        tokens: dict[str, Any] = token_resp.json()

    id_token = tokens.get("id_token")
    if not isinstance(id_token, str):
        return None
    return await asyncio.to_thread(
        _verify_id_token, id_token, metadata["jwks_uri"], metadata["issuer"], stored["nonce"]
    )
