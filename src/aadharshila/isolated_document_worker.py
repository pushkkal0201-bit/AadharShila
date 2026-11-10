"""Bounded PDF parser subprocess, deliberately separate from the HTTP process.

This is process/resource isolation only. It is NOT a kernel sandbox or proof
of malware safety; deployment must additionally use a seccomp/AppArmor profile,
no network, an unprivileged account and an isolated scratch volume.
"""
from __future__ import annotations
import json
import os
import sys

MAX_DOCUMENT_BYTES = 8 * 1024 * 1024


def main() -> int:
    if os.name == 'posix':
        import resource
        # Protect the API host against accidental excessive parser allocation.
        # RLIMIT_AS is not portable to Windows; enforce container memory there.
        memory_limit = 768 * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (memory_limit, memory_limit))
        resource.setrlimit(resource.RLIMIT_CPU, (12, 12))
        resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
    try:
        raw = sys.stdin.buffer.read(MAX_DOCUMENT_BYTES + 1)
        if not raw or len(raw) > MAX_DOCUMENT_BYTES or not raw.startswith(b'%PDF-'):
            raise ValueError('Invalid bounded PDF input')
        # Offline processing only; imported parser never receives provider keys.
        from .documents_pipeline import extract_pdf
        ocr = os.environ.get('AADHARSHILA_WORKER_OCR') == '1'
        result = extract_pdf(raw, ocr_enabled=ocr)
        sys.stdout.write(json.dumps(result, ensure_ascii=True, allow_nan=False))
        return 0
    except BaseException:
        # Avoid reflecting attacker-controlled content or parser traces to API logs.
        sys.stderr.write('DOCUMENT_PARSER_FAILED\n')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
