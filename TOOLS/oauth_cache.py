"""Local OAuth storage. Never print credential contents or include them in CONFIG."""
import json
from functools import partial
import os
from pathlib import Path
import shutil
import tempfile
import uuid

from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

TOKEN_FILE = 'youtube_token.json'


def backup_secret(path):
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return
    folder = path.parent / 'log' / 'oauth-backups'
    folder.mkdir(parents=True, exist_ok=True)
    backup = folder / (path.stem + '-' + uuid.uuid4().hex + '.json')
    shutil.copy2(path, backup)
    if backup.stat().st_size != path.stat().st_size or backup.stat().st_size == 0:
        raise OSError('Could not verify the saved sign-in backup')


def save_credentials(credentials, token_path=TOKEN_FILE):
    path = Path(token_path)
    backup_secret(path)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='youtube-token-', suffix='.tmp', delete=False) as file:
            tmp = file.name
            file.write(credentials.to_json())
            file.flush()
            os.fsync(file.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        tmp = None
    finally:
        if tmp and os.path.exists(tmp):
            os.remove(tmp)


def cached_credentials(scopes, token_path=TOKEN_FILE, client_file='client_secret.json'):
    """Return reusable credentials; never turn a network failure into a new login."""
    try:
        with open(token_path, encoding='utf-8') as file:
            saved = json.load(file)
        with open(client_file, encoding='utf-8') as file:
            client = json.load(file)
        client_id = client.get('installed', {}).get('client_id')
        if not client_id or saved.get('client_id') != client_id:
            return None
        credentials = Credentials.from_authorized_user_info(saved, scopes=scopes)
        if not set(scopes).issubset(set(saved.get('scopes', []))):
            return None
    except (FileNotFoundError, ValueError, TypeError, KeyError):
        return None
    if credentials.valid:
        return credentials
    if credentials.refresh_token:
        try:
            credentials.refresh(partial(Request(), timeout=30))
        except RefreshError as error:
            if getattr(error, 'retryable', False):
                raise RuntimeError('YouTube sign-in refresh is temporarily unavailable. Try again later.') from None
            return None  # Revoked/expired consent needs interactive authorization.
        except TransportError:
            raise RuntimeError('Could not refresh YouTube sign-in. Check the connection and try again.') from None
        if credentials.valid:
            save_credentials(credentials, token_path)
            return credentials
    return None
