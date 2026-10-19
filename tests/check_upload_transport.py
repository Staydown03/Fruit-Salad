"""Offline transport smoke check using FRUIT's installed Google libraries.

Run with the project's .venv Python. No credentials or network requests are used.
"""
import sys
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httplib2
from google.auth.credentials import AnonymousCredentials
from TOOLS import YouTube


def incomplete_response(transport):
    response = httplib2.Response({'status': '308', 'range': 'bytes=0-7'})
    with patch.object(transport, '_conn_request', return_value=(response, b'')):
        return transport._request(Mock(), 'example.invalid', 'https://example.invalid/upload',
                                  '/upload', 'PUT', b'chunk', {}, 5, None)


def main():
    # Reproduce the reported error using the transport from the earlier change.
    try:
        incomplete_response(httplib2.Http(timeout=30))
    except httplib2.RedirectMissingLocation:
        pass
    else:
        raise AssertionError('Expected the old transport to reject the simulated 308')
    with patch.object(YouTube.google_auth_oauthlib.flow.InstalledAppFlow, 'from_client_secrets_file') as flow, \
         patch.object(YouTube.googleapiclient.discovery, 'build') as build, \
         patch.object(YouTube, 'cached_credentials', return_value=None), \
         patch.object(YouTube, 'save_credentials'):
        flow.return_value.run_local_server.return_value = AnonymousCredentials()
        YouTube.authenticate_youtube()
    transport = build.call_args.kwargs['http'].http
    assert transport.timeout == 30
    assert 308 not in transport.redirect_codes
    assert 302 in transport.redirect_codes
    response, _ = incomplete_response(transport)
    assert response.status == 308
    print('Reproduced old redirect error; corrected transport accepts resumable-upload 308 with timeout intact.')


if __name__ == '__main__':
    main()
