#!/usr/bin/env python3
"""Helper script to obtain Dropbox OAuth2 refresh token.

This script helps you get a refresh token for the Dropbox API.
The refresh token is long-lived and can be used to automatically
obtain short-lived access tokens.

Prerequisites:
1. Go to https://www.dropbox.com/developers/apps
2. Create an app (or use existing) with "Full Dropbox" access
3. Go to Permissions tab and enable: files.content.read, files.content.write, sharing.read
4. Have your App key and App secret ready (from Settings tab)
"""

import sys
import json
import urllib.request
import urllib.parse
import webbrowser


def get_authorization_code(app_key: str) -> str:
    """Open browser for authorization and get code."""
    auth_url = "https://www.dropbox.com/oauth2/authorize?" + urllib.parse.urlencode({
        "client_id": app_key,
        "response_type": "code",
        "token_access_type": "offline"
    })

    print("\n" + "="*80)
    print("STEP 1: Authorize the application")
    print("="*80)
    print("\nOpening your browser to authorize the application...")
    print(f"\nIf the browser doesn't open automatically, visit this URL:\n{auth_url}\n")

    try:
        webbrowser.open(auth_url)
    except Exception as e:
        print(f"Could not open browser: {e}")

    print("After authorizing, Dropbox will show you an authorization code.")

    code = input("\nPaste the authorization code here: ").strip()
    if not code:
        raise ValueError("Authorization code is required")
    return code


def exchange_code_for_tokens(app_key: str, app_secret: str, code: str) -> dict:
    """Exchange authorization code for access and refresh tokens."""
    token_url = "https://api.dropboxapi.com/oauth2/token"

    data = urllib.parse.urlencode({
        "client_id": app_key,
        "client_secret": app_secret,
        "code": code,
        "grant_type": "authorization_code"
    }).encode()

    req = urllib.request.Request(token_url, data=data)
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req) as response:
            tokens = json.loads(response.read().decode())
            return tokens
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        raise ValueError(f"Failed to get tokens: {e.code} - {error_body}")


def main():
    """Main function to guide user through OAuth flow."""
    print("="*80)
    print("Dropbox OAuth2 Refresh Token Generator")
    print("="*80)
    print("\nThis script will help you obtain a long-lived refresh token for Dropbox.")
    print("\nPrerequisites:")
    print("  1. Dropbox app at https://www.dropbox.com/developers/apps")
    print("  2. App key and App secret (from Settings tab)")
    print("  3. Permissions enabled: files.content.read, files.content.write, sharing.read")

    input("\nPress Enter to continue...")

    # Get credentials
    print("\n" + "="*80)
    print("Enter your Dropbox app credentials")
    print("="*80)

    app_key = input("\nApp key: ").strip()
    if not app_key:
        print("Error: App key is required")
        sys.exit(1)

    app_secret = input("App secret: ").strip()
    if not app_secret:
        print("Error: App secret is required")
        sys.exit(1)

    try:
        # Get authorization code
        code = get_authorization_code(app_key)

        print("\n" + "="*80)
        print("STEP 2: Exchange code for tokens")
        print("="*80)
        print("\nExchanging authorization code for tokens...")

        # Exchange for tokens
        tokens = exchange_code_for_tokens(app_key, app_secret, code)

        if "refresh_token" not in tokens:
            print("\n" + "="*80)
            print("WARNING: No refresh token received!")
            print("="*80)
            print("\nMake sure token_access_type=offline is set in the auth URL.")
            sys.exit(1)

        # Display results
        print("\n" + "="*80)
        print("SUCCESS! Got your tokens")
        print("="*80)

        print("\n" + "-"*80)
        print("Add these to your .env file:")
        print("-"*80)
        print(f'DROPBOX_APP_KEY={app_key}')
        print(f'DROPBOX_APP_SECRET={app_secret}')
        print(f'DROPBOX_REFRESH_TOKEN={tokens["refresh_token"]}')

        print("\n" + "="*80)
        print("Next steps:")
        print("="*80)
        print("1. Copy the three lines above to your .env file")
        print("2. Remove or comment out DROPBOX_ACCESS_TOKEN if present")
        print("3. Test with: python -m sidekick.clients.dropbox get-metadata /")

        print("\nDone!\n")

    except KeyboardInterrupt:
        print("\n\nAborted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nError: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
