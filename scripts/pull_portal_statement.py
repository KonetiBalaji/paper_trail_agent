"""Fetch a configured portal PDF and submit it to authenticated intake."""
import os
from urllib.parse import urlsplit

import httpx


def pull(portal, intake, statement_url, endpoint):
    limit = 3_900_000
    content = bytearray()
    with portal.stream('GET', statement_url, follow_redirects=False) as response:
        if response.status_code != 200:
            raise RuntimeError(f'Portal returned HTTP {response.status_code}')
        for chunk in response.iter_bytes(chunk_size=65536):
            if len(content) + len(chunk) > limit:
                raise RuntimeError('Portal PDF exceeds the intake size limit')
            content.extend(chunk)
    if not content.startswith(b'%PDF-'):
        raise RuntimeError('Portal did not return a PDF')
    response = intake.post(endpoint, files={'files': ('portal-statement.pdf', bytes(content), 'application/pdf')})
    if response.status_code not in (200, 201):
        raise RuntimeError(f'Portal intake returned HTTP {response.status_code}')
    return response.json()


def main():
    try:
        statement_url = os.environ['PTA_PORTAL_STATEMENT_URL']
        origin = os.environ['PTA_INTAKE_ORIGIN'].rstrip('/')
        statement = urlsplit(statement_url)
        destination = urlsplit(origin)
        for url in (statement, destination):
            if url.scheme != 'https' or not url.hostname or url.username or url.password or url.fragment:
                raise ValueError('Expected an HTTPS URL without embedded credentials')
        if destination.path or destination.query:
            raise ValueError('Intake requires an HTTPS origin')
        with httpx.Client(timeout=30, headers={'Authorization': 'Bearer ' + os.environ['PTA_PORTAL_TOKEN']}) as portal:
            with httpx.Client(timeout=30, headers={'Authorization': 'Bearer ' + os.environ['PTA_INTAKE_KEY']}) as intake:
                receipt = pull(portal, intake, statement_url, origin + '/api/integrations/v1/portal')
        print('Portal statement imported' if receipt['created'] else 'Portal statement already imported')
    except (KeyError, ValueError, RuntimeError, httpx.HTTPError):
        raise SystemExit('Portal intake stopped. Check the configured statement endpoint and credentials.') from None


if __name__ == '__main__':
    main()
