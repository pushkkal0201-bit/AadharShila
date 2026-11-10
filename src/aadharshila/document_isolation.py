"""API-side bounded extraction runner.

Only a minimal process environment is passed and no borrower document is
persisted to a parser scratch directory. The caller must validate and scan
content before it invokes this function.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


class IsolatedExtractionUnavailable(RuntimeError):
    pass


def extract_pdf_isolated(raw: bytes, *, ocr_enabled: bool = False, timeout: int = 20) -> dict:
    if not raw.startswith(b'%PDF-') or not raw or len(raw) > 8 * 1024 * 1024:
        raise IsolatedExtractionUnavailable('INVALID_DOCUMENT')
    if not 1 <= timeout <= 30:
        raise ValueError('Extraction timeout must be bounded')
    allowed_env = ('PATH', 'SYSTEMROOT', 'WINDIR', 'VIRTUAL_ENV', 'PYTHONHOME', 'TMP', 'TEMP', 'LANG')
    env = {key: os.environ[key] for key in allowed_env if key in os.environ}
    # Resolve the installed package location explicitly. The subprocess runs in
    # a disposable directory, so it must not rely on the parent's working dir
    # or on a caller-controlled PYTHONPATH for module discovery.
    env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1])
    env['AADHARSHILA_WORKER_OCR'] = '1' if ocr_enabled else '0'
    with tempfile.TemporaryDirectory(prefix='aadharshila-pdf-') as scratch:
        try:
            child = subprocess.run([sys.executable, '-m', 'aadharshila.isolated_document_worker'],
                                   input=raw, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   cwd=scratch, env=env, timeout=timeout, check=False)
        except (subprocess.TimeoutExpired, OSError):
            raise IsolatedExtractionUnavailable('DOCUMENT_PARSER_TIMEOUT_OR_UNAVAILABLE') from None
    if child.returncode != 0 or len(child.stdout) > 128 * 1024:
        raise IsolatedExtractionUnavailable('DOCUMENT_PARSER_FAILED')
    try:
        result = json.loads(child.stdout)
        if not isinstance(result, dict) or result.get('status') not in {
            'PARSED', 'NEEDS_OCR', 'OCR_EXTRACTED', 'EXTRACTION_FAILED',
            'PASSWORD_PROTECTED', 'PAGE_LIMIT_EXCEEDED'}:
            raise ValueError('Unexpected parser schema')
        return result
    except (ValueError, UnicodeDecodeError):
        raise IsolatedExtractionUnavailable('DOCUMENT_PARSER_INVALID_RESPONSE') from None
