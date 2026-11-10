"""Pinned-issuer, pinned-audience OIDC bearer token verification (API only).

User provisioning, MFA policy and role assignment remain owned by the lender.
No automatic creation of users from token claims is permitted.
"""
from __future__ import annotations
import json, os
from pathlib import Path
import jwt


class FederatedAuthenticationError(ValueError):
    pass


def validate_federated_token(token: str) -> dict:
    issuer=os.getenv('OIDC_ISSUER','')
    audience=os.getenv('OIDC_AUDIENCE','')
    jwks_path=os.getenv('OIDC_JWKS_PATH','')
    if not all((issuer,audience,jwks_path)) or not issuer.startswith('https://'):
        raise FederatedAuthenticationError('Identity provider not configured')
    try:
        jwks=json.loads(Path(jwks_path).read_text(encoding='utf-8'))
        keys=jwks['keys']
        header=jwt.get_unverified_header(token)
        if header.get('alg')!='RS256' or not header.get('kid'):
            raise FederatedAuthenticationError('Unsupported token header')
        matched=[k for k in keys if k.get('kid')==header['kid'] and k.get('kty')=='RSA'
                 and k.get('use','sig')=='sig' and k.get('alg','RS256')=='RS256']
        if len(matched)!=1:raise FederatedAuthenticationError('Unknown identity-provider signing key')
        key=jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(matched[0]))
        claims=jwt.decode(token,key,algorithms=['RS256'],issuer=issuer,audience=audience,
                          options={'require':['sub','iss','aud','exp','iat']},leeway=30)
        if not isinstance(claims.get('sub'),str) or not claims['sub']:
            raise FederatedAuthenticationError('Missing subject')
        expected_acr=os.getenv('OIDC_REQUIRED_ACR','')
        if expected_acr and claims.get('acr')!=expected_acr:
            raise FederatedAuthenticationError('Required authentication assurance missing')
        if os.getenv('OIDC_REQUIRE_MFA','true').lower()=='true' and 'mfa' not in claims.get('amr',[]):
            raise FederatedAuthenticationError('MFA authentication evidence missing')
        return claims
    except (OSError,KeyError,TypeError,ValueError,jwt.PyJWTError) as exc:
        if isinstance(exc,FederatedAuthenticationError):raise
        raise FederatedAuthenticationError('Invalid identity-provider token or configuration') from None
