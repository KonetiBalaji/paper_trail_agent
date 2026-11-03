"""Poll a dedicated IMAP folder once and submit messages to Paper Trail Agent."""
import argparse
import imaplib
import json
import os
import re
import ssl
from pathlib import Path
from urllib.parse import urlsplit

import httpx


def poll(mailbox, client, endpoint, cursor_path, scope):
    status, values = mailbox.response('UIDVALIDITY')
    if status != 'UIDVALIDITY' or len(values) != 1 or not values[0] or not values[0].isdigit():
        raise RuntimeError('Mailbox UID validity is unavailable')
    identity = [*scope, int(values[0])]
    cursor = 0
    if cursor_path.exists():
        saved = json.loads(cursor_path.read_text(encoding='utf-8'))
        if saved['identity'] != identity:
            raise RuntimeError('Mailbox identity changed. Review the cursor before resuming.')
        cursor = int(saved['uid'])
    status, messages = mailbox.uid('SEARCH', None, 'UID', f'{cursor + 1}:*')
    if status != 'OK':
        raise RuntimeError('Mailbox search failed')
    processed = 0
    for uid in sorted(int(value) for value in messages[0].split() if value.isdigit()):
        if uid <= cursor:
            continue
        status, parts = mailbox.uid('FETCH', str(uid), '(BODY.PEEK[]<0.4000001>)')
        if status != 'OK':
            raise RuntimeError('Mailbox message fetch failed')
        payloads = [part[1] for part in parts if isinstance(part, tuple)]
        if len(payloads) != 1 or not re.search(rb'\bUID ' + str(uid).encode() + rb'\b',
                                                  next(part[0] for part in parts if isinstance(part, tuple))):
            raise RuntimeError('Mailbox returned an unexpected message')
        if len(payloads[0]) > 4_000_000:
            raise RuntimeError('Mailbox message exceeds the intake size limit')
        result = client.post(endpoint, files={'message': ('statement.eml', payloads[0], 'message/rfc822')})
        if result.status_code not in (200, 201):
            raise RuntimeError(f'Email intake returned HTTP {result.status_code}')
        temporary = cursor_path.with_suffix(cursor_path.suffix + '.tmp')
        temporary.write_text(json.dumps({'identity': identity, 'uid': uid}), encoding='utf-8')
        temporary.replace(cursor_path)
        cursor = uid
        processed += 1
        if processed == 10:
            break
    return processed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cursor', required=True, type=Path)
    args = parser.parse_args()
    try:
        host = os.environ['PTA_IMAP_HOST']
        username = os.environ['PTA_IMAP_USER']
        folder = os.environ['PTA_IMAP_FOLDER']
        origin = os.environ['PTA_INTAKE_ORIGIN'].rstrip('/')
        url = urlsplit(origin)
        if url.scheme != 'https' or not url.hostname or url.username or url.path or url.query or url.fragment:
            raise RuntimeError('Intake origin must be an HTTPS origin')
        with imaplib.IMAP4_SSL(host, ssl_context=ssl.create_default_context(), timeout=15) as mailbox:
            mailbox.login(username, os.environ['PTA_IMAP_PASSWORD'])
            status, _ = mailbox.select(folder, readonly=True)
            if status != 'OK':
                raise RuntimeError('Dedicated mailbox folder is unavailable')
            with httpx.Client(timeout=30, headers={'Authorization': 'Bearer ' + os.environ['PTA_INTAKE_KEY']}) as client:
                count = poll(mailbox, client, origin + '/api/integrations/v1/email', args.cursor,
                             [host, username, folder, origin])
        print(f'Processed {count} mailbox messages')
    except (KeyError, RuntimeError, OSError, imaplib.IMAP4.error, httpx.HTTPError, ValueError):
        raise SystemExit('Mailbox intake stopped. Check connector configuration and the next unread cursor position.') from None


if __name__ == '__main__':
    main()
