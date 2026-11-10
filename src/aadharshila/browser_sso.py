"""OIDC authorization-code / PKCE browser sign-in for pre-provisioned users.

No self-service account registration, no token trust without pinned issuer JWKS,
no dynamic redirect URI, and no local password login in production.
"""
from __future__ import annotations
from .runtime import is_production
import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlsplit
import httpx
import jwt
from .federated_auth import validate_federated_token, FederatedAuthenticationError

class BrowserSSOError(ValueError):
    pass


def validate_endpoints() -> tuple[str,str,str,str]:
    issuer=os.getenv('OIDC_ISSUER','')
    auth=os.getenv('OIDC_AUTHORIZATION_ENDPOINT','')
    token=os.getenv('OIDC_TOKEN_ENDPOINT','')
    redirect=os.getenv('OIDC_REDIRECT_URI','')
    client=os.getenv('OIDC_CLIENT_ID','')
    parsed=urlsplit(issuer)
    if not client or not issuer or parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:
        raise BrowserSSOError('Lender OIDC identity provider not configured')
    for endpoint in (auth, token):
        addr=urlsplit(endpoint)
        if addr.scheme!='https' or addr.hostname!=parsed.hostname or addr.port not in (None,443) or addr.username or addr.password or addr.fragment or addr.query:
            raise BrowserSSOError('OIDC endpoint must use the pinned identity-provider HTTPS host')
    callback=urlsplit(redirect)
    if callback.path!='/api/v1/auth/oidc/callback' or callback.fragment or callback.query or callback.username or callback.password:
        raise BrowserSSOError('Invalid fixed OIDC redirect URI')
    if callback.scheme!='https' and not (not is_production() and
                                          callback.scheme=='http' and callback.hostname in ('127.0.0.1','localhost')):
        raise BrowserSSOError('OIDC redirect must use HTTPS')
    return auth,token,redirect,client


def _pkce(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).rstrip(b'=').decode('ascii')


def begin(secret: str) -> tuple[str,str]:
    auth,_,callback,client=validate_endpoints()
    state=secrets.token_urlsafe(32)
    nonce=secrets.token_urlsafe(32)
    verifier=secrets.token_urlsafe(48)
    now=datetime.now(timezone.utc)
    cookie=jwt.encode({'purpose':'oidc_login','state':state,'nonce':nonce,'verifier':verifier,
                       'iat':now,'exp':now+timedelta(minutes=5)},secret,algorithm='HS256')
    params={'client_id':client,'redirect_uri':callback,'response_type':'code','scope':'openid profile',
            'state':state,'nonce':nonce,'code_challenge':_pkce(verifier),'code_challenge_method':'S256'}
    return auth+'?'+urlencode(params),cookie


def consume_flow(cookie: str|None,state: str, secret: str) -> dict:
    if not cookie or not state or len(state)>180:
        raise BrowserSSOError('Missing or expired login state')
    try:
        payload=jwt.decode(cookie,secret,algorithms=['HS256'],options={'require':['purpose','state','nonce','verifier','exp','iat']})
    except jwt.PyJWTError:
        raise BrowserSSOError('Invalid or expired login state') from None
    if payload['purpose']!='oidc_login' or not hmac.compare_digest(payload['state'],state):
        raise BrowserSSOError('OIDC login state does not match')
    return payload


def exchange_authorization_code(code: str, verifier: str, nonce: str) -> tuple[dict, int]:
    _,token_url,callback,client=validate_endpoints()
    secret=os.getenv('OIDC_CLIENT_SECRET','')
    if not secret or len(code)>4096 or not code:
        raise BrowserSSOError('OIDC code exchange not configured')
    try:
        # No redirects, proxies from environment, or arbitrary external destinations.
        with httpx.Client(follow_redirects=False,timeout=httpx.Timeout(5.0,connect=3.0),trust_env=False) as http:
            reply=http.post(token_url, auth=httpx.BasicAuth(client,secret), data={
                'grant_type':'authorization_code','code':code,'redirect_uri':callback,'code_verifier':verifier},
                headers={'Accept':'application/json'})
        if reply.status_code!=200 or len(reply.content)>65536:
            raise BrowserSSOError('Identity provider did not complete authentication')
        body=reply.json()
        id_token=body.get('id_token')
        if not isinstance(id_token,str):
            raise BrowserSSOError('Missing signed ID token')
        claims=validate_federated_token(id_token)
        if not isinstance(claims.get('nonce'),str) or not hmac.compare_digest(claims['nonce'],nonce):
            raise BrowserSSOError('OIDC nonce mismatch')
        # Restrict the browser session to the signed ID-token lifetime.
        remaining=int(claims['exp']-datetime.now(timezone.utc).timestamp())
        if remaining<=0:raise BrowserSSOError('Identity assertion has expired')
        return claims,min(remaining,3600)
    except (httpx.HTTPError,ValueError,KeyError,TypeError,FederatedAuthenticationError):
        raise BrowserSSOError('Identity-provider verification failed') from None


def new_opaque_session() -> tuple[str,str]:
    raw='fs_'+secrets.token_urlsafe(40)
    return raw,hashlib.sha256(raw.encode('utf-8')).hexdigest()
