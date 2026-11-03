"""Extract PDF attachments from an authenticated connector's MIME message."""
from email import policy
from email.parser import BytesParser
from io import BytesIO

from fastapi import HTTPException, UploadFile


def pdf_attachments(message: UploadFile) -> list[UploadFile]:
    limit = 4_000_000
    raw = message.file.read(limit + 1)
    if len(raw) > limit:
        raise HTTPException(413, 'Email exceeds the 4 MB intake limit')
    try:
        parsed = BytesParser(policy=policy.default).parsebytes(raw)
        files = []
        for index, part in enumerate(parsed.walk()):
            if index >= 100:
                raise HTTPException(422, 'Email contains too many MIME parts')
            if part.is_multipart() or part.get_content_disposition() != 'attachment':
                continue
            if part.get_content_type() != 'application/pdf':
                continue
            payload = part.get_payload(decode=True)
            if part.defects or not payload or not payload.startswith(b'%PDF-'):
                raise HTTPException(422, 'Invalid PDF attachment')
            if len(files) == 8:
                raise HTTPException(422, 'Email contains more than eight PDF attachments')
            files.append(UploadFile(filename=f'attachment-{len(files) + 1}.pdf', file=BytesIO(payload)))
    except (RecursionError, ValueError, LookupError) as exc:
        raise HTTPException(422, 'Invalid MIME message') from exc
    if not files:
        raise HTTPException(422, 'Email contains no PDF attachments')
    return files
