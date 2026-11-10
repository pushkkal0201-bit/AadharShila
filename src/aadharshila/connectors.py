"""Consent-bound evidence collection with a fail-closed partner-gateway contract.

This is NOT a direct integration with a bureau, CKYCR, DigiLocker or other
regulated source. Those require onboarding, approval and provider-specific
contracts. A configured gateway can be used only after such authorization.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from urllib.parse import urlsplit
import hashlib
import hmac
import ipaddress
import json
import os
import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Evidence, Application, Consent, ProviderInvocation
from .service import bump, build_assessment, audit

SUPPORTED_KEYS = {'identity', 'bank_income', 'income_support', 'bureau', 'ownership', 'legal', 'valuation', 'screening', 'bank_transactions', 'ckyc', 'digilocker', 'account_aggregator', 'gst', 'property_registry', 'cersai', 'rera'}
REQUIRED_PURPOSE = 'financial_underwriting'


@dataclass(frozen=True)
class ConnectorResult:
    mode: str
    status: str
    verification: str
    provider: str
    value: dict
    error_category: str | None = None
    signature_validated: bool = False
    verified_at: str | None = None


class Connector(Protocol):
    mode: str
    def fetch(self, db: Session, application: Application, key: str, request_id: str) -> ConnectorResult: ...


class DeterministicFixtureConnector:
    mode = 'SIMULATED'

    def fetch(self, db: Session, application: Application, key: str, request_id: str) -> ConnectorResult:
        original = db.scalar(
            select(Evidence).where(
                Evidence.application_id == application.id,
                Evidence.key == key,
                Evidence.provider == 'synthetic-fixture-v1',
                Evidence.mode == 'SIMULATED',
            ).order_by(Evidence.captured_at.desc(), Evidence.revision.desc())
        )
        if original is None:
            return ConnectorResult('UNAVAILABLE', 'UNRESOLVED', 'FAILED', 'unconfigured-provider',
                                   {'error': 'NO_AUTHORIZED_FIXTURE'}, 'PROVIDER_NOT_CONFIGURED')
        if original.verification == 'FAILED':
            return ConnectorResult('SIMULATED', 'UNRESOLVED', 'FAILED', 'synthetic-fixture-v1',
                                   {'error': 'UPSTREAM_UNAVAILABLE'}, 'SIMULATED_PROVIDER_FAILURE')
        return ConnectorResult('SIMULATED', 'SUCCESS', original.verification,
                               'synthetic-fixture-v1', original.value)


class GatewayConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class GatewayConfig:
    url: str
    token: str
    hmac_key: str
    provider: str
    mode: str
    allowed_hosts: frozenset[str]

    @classmethod
    def for_key(cls, key: str):
        if key not in SUPPORTED_KEYS:
            raise GatewayConfigurationError('Unsupported evidence operation')
        prefix = 'AADHARSHILA_PARTNER_' + key.upper() + '_'
        url = os.getenv(prefix + 'URL', '')
        if not url:
            return None
        mode = os.getenv(prefix + 'MODE', 'SANDBOX').upper()
        token = os.getenv(prefix + 'TOKEN', '')
        key_material = os.getenv(prefix + 'HMAC_KEY', '')
        provider = os.getenv(prefix + 'NAME', '')
        hosts = frozenset(s.strip().lower() for s in os.getenv('AADHARSHILA_PARTNER_ALLOWED_HOSTS', '').split(',') if s.strip())
        config = cls(url, token, key_material, provider, mode, hosts)
        config.validate()
        return config

    def validate(self):
        parts = urlsplit(self.url)
        host = (parts.hostname or '').lower()
        if parts.scheme != 'https' or parts.username or parts.password or parts.fragment or parts.query:
            raise GatewayConfigurationError('Partner URL must be a fixed HTTPS endpoint without URL credentials, query or fragment')
        if not host or host not in self.allowed_hosts or host == 'localhost' or host.endswith('.local'):
            raise GatewayConfigurationError('Partner host is not explicitly allowlisted')
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise GatewayConfigurationError('Literal IP addresses are forbidden for outbound partner calls')
        if parts.port not in (None, 443):
            raise GatewayConfigurationError('Partner gateway must use HTTPS port 443')
        if self.mode not in ('LIVE', 'SANDBOX') or not self.provider.strip():
            raise GatewayConfigurationError('Explicit provider name and LIVE/SANDBOX mode required')
        if len(self.token) < 16 or len(self.hmac_key) < 32:
            raise GatewayConfigurationError('Partner credentials and response-signing secret required')
        if os.getenv('APP_ENV', 'development') == 'production' and self.mode != 'LIVE':
            raise GatewayConfigurationError('SANDBOX providers cannot be used as production sources')


class PartnerGatewayConnector:
    """Signed response from a trusted, pre-onboarded partner gateway only.

    The response schema is Aadharshila's *own* gateway contract; it is not an
    assertion that any government registry or bureau implements this API.
    """
    def __init__(self, config: GatewayConfig, transport=None):
        config.validate()
        self.config = config
        self.mode = config.mode
        self.transport = transport

    def fetch(self, db: Session, application: Application, key: str, request_id: str) -> ConnectorResult:
        cfg = self.config
        payload = {'request_id': request_id, 'application_reference': application.reference,
                   'evidence_key': key, 'purpose': REQUIRED_PURPOSE}
        # The adapter sends a case reference, not identities, addresses or original documents.
        try:
            with httpx.Client(timeout=httpx.Timeout(5, connect=2), follow_redirects=False,
                              transport=self.transport, trust_env=False) as client:
                response = client.post(cfg.url, json=payload, headers={
                    'Authorization': f'Bearer {cfg.token}', 'X-Correlation-ID': request_id,
                    'Accept': 'application/json'})
            if 300 <= response.status_code < 400:
                raise ValueError('REDIRECT_REJECTED')
            if response.status_code >= 500 or response.status_code == 429:
                raise ValueError('PROVIDER_UNAVAILABLE')
            if response.status_code != 200:
                raise ValueError('PROVIDER_DENIED')
            if len(response.content) > 100_000:
                raise ValueError('RESPONSE_OVERSIZED')
            signature = response.headers.get('X-Aadharshila-Signature', '')
            expected = hmac.new(cfg.hmac_key.encode(), response.content, hashlib.sha256).hexdigest()
            if not signature or not hmac.compare_digest(signature, expected):
                raise ValueError('INVALID_SIGNATURE')
            body = response.json()
            if not isinstance(body, dict) or body.get('request_id') != request_id:
                raise ValueError('RESPONSE_CORRELATION_MISMATCH')
            if body.get('verification') not in ('VERIFIED', 'UNRESOLVED', 'FAILED'):
                raise ValueError('INVALID_VERIFICATION_STATUS')
            supplied_at = datetime.fromisoformat(str(body.get('verified_at', '')).replace('Z', '+00:00'))
            if supplied_at.tzinfo is None or abs((datetime.now(timezone.utc) - supplied_at).total_seconds()) > 300:
                raise ValueError('STALE_PROVIDER_ASSERTION')
            data = body.get('data')
            if not isinstance(data, dict):
                raise ValueError('INVALID_RESPONSE_PAYLOAD')
            try:
                serialized = json.dumps(data, sort_keys=True, separators=(',', ':'), allow_nan=False)
            except (TypeError, ValueError):
                raise ValueError('INVALID_RESPONSE_PAYLOAD') from None
            if len(serialized.encode('utf-8')) > 20_000:
                raise ValueError('INVALID_RESPONSE_PAYLOAD')
            return ConnectorResult(cfg.mode, 'SUCCESS', body['verification'], cfg.provider,
                                   data, None, True, supplied_at.isoformat())
        except (httpx.HTTPError, ValueError, TypeError, OverflowError, json.JSONDecodeError) as error:
            if isinstance(error, httpx.TimeoutException):
                category = 'PROVIDER_TIMEOUT'
            elif isinstance(error, httpx.HTTPError):
                category = 'PROVIDER_TRANSPORT_FAILURE'
            else:
                category = str(error) if str(error) in {
                    'REDIRECT_REJECTED', 'PROVIDER_UNAVAILABLE', 'PROVIDER_DENIED',
                    'RESPONSE_OVERSIZED', 'INVALID_SIGNATURE', 'RESPONSE_CORRELATION_MISMATCH',
                    'INVALID_VERIFICATION_STATUS', 'STALE_PROVIDER_ASSERTION',
                    'INVALID_RESPONSE_PAYLOAD'} else 'INVALID_PROVIDER_RESPONSE'
            return ConnectorResult(cfg.mode, 'UNRESOLVED', 'FAILED', cfg.provider,
                                   {'error': category}, category)


def consent_authorized(db, app, *, evidence_key=None, provider=None, mode=None):
    now = datetime.now(timezone.utc)
    for consent in db.scalars(select(Consent).where(
            Consent.application_id == app.id,
            Consent.purpose == REQUIRED_PURPOSE,
            Consent.revoked_at.is_(None))):
        expiry = consent.expires_at
        if expiry and expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if expiry and expiry<=now:continue
        if mode=='LIVE' or (mode=='SANDBOX' and os.getenv('APP_ENV','development')=='production'):
            # A broad loan consent is insufficient for a regulated third-party
            # retrieval. The borrower must grant this provider and category.
            if consent.subject_id!=app.owner_id or consent.provider!=provider or evidence_key not in (consent.categories or []):
                continue
        return True
    return False


def configured_adapter(key):
    try:
        config = GatewayConfig.for_key(key)
    except GatewayConfigurationError:
        return None, 'GATEWAY_CONFIGURATION_INVALID'
    if config:
        return PartnerGatewayConnector(config), None
    if os.getenv('APP_ENV', 'development') == 'production':
        return None, 'PROVIDER_NOT_CONFIGURED'
    return DeterministicFixtureConnector(), None


def fetch_and_record(db, app, key, actor):
    if key not in SUPPORTED_KEYS:
        raise ValueError('Unsupported provider operation')
    request_id = str(uuid.uuid4())
    adapter, config_error = configured_adapter(key)
    provider = getattr(getattr(adapter,'config',None),'provider',None)
    mode = getattr(adapter,'mode',None)
    if not consent_authorized(db,app,evidence_key=key,provider=provider,mode=mode):
        raise PermissionError('Active, purpose-specific borrower/provider consent required')
    if adapter is None:
        reply = ConnectorResult('UNAVAILABLE', 'UNRESOLVED', 'FAILED', 'unconfigured-provider',
                                {'error': config_error}, config_error)
    else:
        reply = adapter.fetch(db, app, key, request_id)
    invocation = ProviderInvocation(application_id=app.id, evidence_key=key,
        provider_name=reply.provider, mode=reply.mode,
        status=reply.status, request_id=request_id, error_category=reply.error_category,
        response_metadata={'verification': reply.verification, 'typed_error': reply.error_category,
                           'live': reply.mode == 'LIVE', 'signature_validated': reply.signature_validated,
                           'payload_sha256': (hashlib.sha256(json.dumps(reply.value, sort_keys=True,
                               separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()
                               if reply.signature_validated and reply.status == 'SUCCESS' else None),
                           'verified_at': reply.verified_at},
        completed_at=datetime.now(timezone.utc))
    db.add(invocation)
    db.flush()
    bump(db, app, actor, 'Provider refresh: ' + key)
    row = Evidence(application_id=app.id, key=key, value=reply.value,
        provider=reply.provider, mode=reply.mode,
        verification=reply.verification, revision=app.revision,
        provider_invocation_id=invocation.id,
        expires_at=(datetime.now(timezone.utc) + __import__('datetime').timedelta(hours=24))
        if reply.mode in ('LIVE', 'SANDBOX') else None)
    db.add(row)
    db.flush()
    assessment = build_assessment(db, app, actor) if app.workflow != 'DRAFT' else None
    audit(db, app.id, actor, 'CONNECTOR_INVOKED', detail={
        'request_id': request_id, 'provider': reply.provider,
        'mode': reply.mode, 'status': reply.status,
        'error_category': reply.error_category})
    db.flush()
    return {'invocation_id': invocation.id, 'request_id': request_id,
            'mode': reply.mode, 'status': reply.status, 'verification': reply.verification,
            'error_category': reply.error_category,
            'assessment_id': assessment.id if assessment else None,
            'message': 'Signed configured partner gateway response.' if reply.mode in ('LIVE', 'SANDBOX')
                        else 'Local deterministic fixture or unavailable dependency; no provider contacted.'}
