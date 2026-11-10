"""Optional document intelligence tools; unverifiable checks fail closed.

The file is untrusted. OCR content is extraction, never issuer verification.
Production uploads need an actual ClamAV-compatible scanning service.
"""
from __future__ import annotations
import io, os, socket, struct
from pathlib import Path
from typing import Optional

class DocumentSafetyError(Exception):
    pass


def clamav_scan(raw: bytes, socket_path: str | None = None) -> str:
    """ClamAV INSTREAM protocol; raises if scanner unavailable or response ambiguous."""
    socket_path=socket_path or os.getenv('CLAMAV_UNIX_SOCKET')
    if not socket_path:
        return 'NOT_PERFORMED'
    if len(raw)>8*1024*1024:
        raise DocumentSafetyError('UPLOAD_TOO_LARGE')
    # Windows Python builds may omit AF_UNIX entirely. Explicitly report the
    # unavailable scanner rather than crashing or treating an upload as clean.
    if not hasattr(socket,'AF_UNIX'):
        raise DocumentSafetyError('MALWARE_SCANNER_UNAVAILABLE')
    try:
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as connection:
            connection.settimeout(8)
            connection.connect(socket_path)
            connection.sendall(b'zINSTREAM\0')
            for offset in range(0,len(raw),65536):
                part=raw[offset:offset+65536]
                connection.sendall(struct.pack('!I',len(part))+part)
            connection.sendall(struct.pack('!I',0))
            result=connection.recv(1024).decode('utf-8','replace')
    except (OSError, UnicodeError, ValueError):
        raise DocumentSafetyError('MALWARE_SCANNER_UNAVAILABLE') from None
    if result.strip('\x00\n\r ')=='stream: OK':return 'CLEAN'
    if result.startswith('stream:') and result.rstrip('\0\n').endswith('FOUND'):
        raise DocumentSafetyError('MALWARE_DETECTED')
    raise DocumentSafetyError('MALWARE_SCAN_INCONCLUSIVE')


def extract_pdf(raw: bytes, *, ocr_enabled: bool=False, max_pages: int=30) -> dict:
    """Text + optionally OCR text (Tesseract/pdfium); mark signature unverified."""
    from pypdf import PdfReader
    try:
        reader=PdfReader(io.BytesIO(raw),strict=False)
        if reader.is_encrypted:
            return {'status':'PASSWORD_PROTECTED','text':'','signature':'NOT_PERFORMED','ocr':'NOT_PERFORMED','page_count':len(reader.pages)}
        if len(reader.pages)>max_pages:
            return {'status':'PAGE_LIMIT_EXCEEDED','text':'','signature':'NOT_PERFORMED','ocr':'NOT_PERFORMED','page_count':len(reader.pages)}
        text_parts=[page.extract_text() or '' for page in reader.pages]
        signature='DETECTED_NOT_VALIDATED' if '/Sig' in str(reader.get_fields() or {}) else 'NOT_PERFORMED'
        result={'status':'PARSED' if any(s.strip() for s in text_parts) else 'NEEDS_OCR',
                'text':'\n'.join(text_parts)[:40000], 'signature':signature,
                'ocr':'NOT_PERFORMED','page_count':len(reader.pages)}
        if result['status']!='NEEDS_OCR' or not ocr_enabled:return result
        try:
            import pypdfium2 as pdfium
            import pytesseract
            pdf=pdfium.PdfDocument(raw)
            collected=[]
            for page in pdf:
                image=page.render(scale=1.5).to_pil()
                collected.append(pytesseract.image_to_string(image,timeout=8))
            result['text']='\n'.join(collected)[:40000]
            result['ocr']='TESSERACT'
            result['status']='OCR_EXTRACTED' if result['text'].strip() else 'NEEDS_OCR'
        except (ImportError,RuntimeError,ValueError,OSError) as exc:
            result['ocr']='UNAVAILABLE';result['status']='NEEDS_OCR'
        return result
    except (ValueError,KeyError,TypeError,RuntimeError) as exc:
        return {'status':'EXTRACTION_FAILED','text':'','signature':'NOT_PERFORMED','ocr':'NOT_PERFORMED',
                'error':type(exc).__name__}
