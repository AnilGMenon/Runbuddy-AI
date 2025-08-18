"""Google OAuth helper functions.

- Robust offline access with refresh tokens.
- Auto re-consent when refresh token is expired/revoked.
- Stores token.json next to project root.
"""

from pathlib import Path
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError

from ..config import SCOPES

def authenticate_google_api(base_dir: Path | None = None) -> Credentials:
    """Authenticate with Google APIs using OAuth2.

    - Loads saved token.json if available.
    - Refreshes token if expired.
    - Falls back to full interactive flow when needed.

    :param base_dir: Optional path override for where token.json/credentials.json live.
    :return: Valid Google Credentials object.
    """
    import os
    from pathlib import Path

    base_dir = base_dir or Path(__file__).resolve().parents[2]  # project root guess
    token_path = base_dir / "token.json"
    client_secret_path = base_dir / "credentials.json"

    if not client_secret_path.exists():
        raise FileNotFoundError(
            f"Missing {client_secret_path.name}. "
            "Place your OAuth 'Desktop app' credentials here."
        )

    creds = None
    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        except Exception:
            # If the token file is corrupted or incompatible, remove it
            token_path.unlink(missing_ok=True)

    def _run_flow() -> Credentials:
        """Run the interactive OAuth flow to obtain new credentials.

        :return: Fresh Credentials object after user consents.
        """
        flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_path), SCOPES)
        creds = flow.run_local_server(
            host="localhost",
            port=0,
            open_browser=True,
            authorization_prompt_message="",
            success_message="Authentication complete.",
            access_type="offline",
            prompt="consent",
            include_granted_scopes="true",
        )
        token_path.write_text(creds.to_json())
        return creds

    if not creds:
        # No saved creds → force interactive flow
        creds = _run_flow()
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            # Attempt to refresh token
            creds.refresh(Request())
            token_path.write_text(creds.to_json())
            return creds
        except RefreshError:
            # Refresh token invalid/expired → interactive flow again
            token_path.unlink(missing_ok=True)
            return _run_flow()

    if creds.valid:
        return creds

    # Catch-all fallback
    return _run_flow()
