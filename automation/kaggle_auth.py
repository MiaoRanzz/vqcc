"""Load the SDK credential without overriding Codex's MCP OAuth login."""
from pathlib import Path


def load_kaggle_api_token(environment, token_path=None):
    token = environment.get('KAGGLE_API_TOKEN')
    if not token:
        path = Path(token_path) if token_path else Path.home() / '.kaggle/access_token'
        if path.is_file():
            token = path.read_text().strip()
    if not token:
        return
    environment['KAGGLE_API_TOKEN'] = token
