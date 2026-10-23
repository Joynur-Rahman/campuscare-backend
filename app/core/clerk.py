from functools import lru_cache

import jwt
from fastapi import Header, HTTPException

from app.core.config import settings


@lru_cache(maxsize=1)
def jwks_client() -> jwt.PyJWKClient:
    return jwt.PyJWKClient(settings.clerk_jwks_url)


def get_current_claims(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")

    token = authorization.removeprefix("Bearer ").strip()
    try:
        decode_options = {"verify_aud": False}
        decode_kwargs = {
            "algorithms": ["RS256"],
            "issuer": settings.clerk_issuer,
        }
        if settings.clerk_audience:
            decode_options["verify_aud"] = True
            decode_kwargs["audience"] = settings.clerk_audience

        signing_key = jwks_client().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            options=decode_options,
            **decode_kwargs,
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid Clerk token") from exc

    if not claims.get("sub"):
        raise HTTPException(status_code=401, detail="Clerk token has no subject")
    return claims