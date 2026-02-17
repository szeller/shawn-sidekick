#!/usr/bin/env python3
"""Helper script to obtain Microsoft OAuth2 refresh token.

This script helps you get a refresh token for Microsoft To Do (via Graph API).

Prerequisites:
1. Go to https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps/ApplicationsListBlade
2. Register a new application (or use existing)
3. Set platform to "Mobile and desktop applications" with redirect URI http://localhost
4. Under API permissions, add Microsoft Graph > Delegated > Tasks.ReadWrite
5. Have your Application (client) ID ready
"""

import sys
import json
import urllib.request
import urllib.parse
import webbrowser


def get_authorization_code(client_id: str) -> str:
    """Open browser for authorization and get code."""
    redirect_uri = "http://localhost"

    scope = "Tasks.ReadWrite offline_access"

    auth_url = "https://login.microsoftonline.com/consumers/oauth2/v2.0/authorize?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scope,
        "prompt": "consent"
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

    print("\nAfter authorizing, you'll be redirected to a URL like:")
    print("  http://localhost/?code=M.C528_BAY...")
    print("\nThe page won't load (that's expected). Copy the ENTIRE URL from your browser's address bar.")

    redirect_url = input("\nPaste the redirect URL here: ").strip()

    # Extract code from URL
    if "code=" in redirect_url:
        code = redirect_url.split("code=")[1].split("&")[0]
        return code
    else:
        raise ValueError("Could not find authorization code in URL")


def exchange_code_for_tokens(client_id: str, code: str, client_secret: str = None) -> dict:
    """Exchange authorization code for access and refresh tokens."""
    token_url = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
    redirect_uri = "http://localhost"

    token_data = {
        "client_id": client_id,
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
        "scope": "Tasks.ReadWrite offline_access"
    }
    if client_secret:
        token_data["client_secret"] = client_secret

    data = urllib.parse.urlencode(token_data).encode()

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
    print("Microsoft To Do OAuth2 Refresh Token Generator")
    print("="*80)
    print("\nThis script will help you obtain a refresh token for Microsoft To Do.")
    print("\nPrerequisites:")
    print("  1. Azure AD app registration with redirect URI http://localhost")
    print("     (Platform: Mobile and desktop applications)")
    print("  2. API permission: Microsoft Graph > Delegated > Tasks.ReadWrite")
    print("  3. Application (client) ID ready")
    print("\nIf you don't have these, visit:")
    print("  https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps/ApplicationsListBlade")

    input("\nPress Enter to continue...")

    # Get credentials
    print("\n" + "="*80)
    print("Enter your Azure AD app credentials")
    print("="*80)

    client_id = input("\nApplication (client) ID: ").strip()
    if not client_id:
        print("Error: Client ID is required")
        sys.exit(1)

    client_secret = input("Client Secret (press Enter to skip for public clients): ").strip()

    try:
        # Get authorization code
        code = get_authorization_code(client_id)

        print("\n" + "="*80)
        print("STEP 2: Exchange code for tokens")
        print("="*80)
        print("\nExchanging authorization code for tokens...")

        # Exchange for tokens
        tokens = exchange_code_for_tokens(client_id, code, client_secret or None)

        if "refresh_token" not in tokens:
            print("\n" + "="*80)
            print("WARNING: No refresh token received!")
            print("="*80)
            print("\nMake sure 'offline_access' is included in the scope.")
            print("Also check that your Azure AD app has the correct API permissions.")
            sys.exit(1)

        # Display results
        print("\n" + "="*80)
        print("SUCCESS! Got your tokens")
        print("="*80)

        print("\n" + "-"*80)
        print("Refresh Token (save this!):")
        print("-"*80)
        print(tokens["refresh_token"])

        print("\n" + "-"*80)
        print("Add these to your .env file:")
        print("-"*80)
        print(f'MICROSOFT_CLIENT_ID={client_id}')
        if client_secret:
            print(f'MICROSOFT_CLIENT_SECRET={client_secret}')
        print(f'MICROSOFT_REFRESH_TOKEN={tokens["refresh_token"]}')

        print("\n" + "="*80)
        print("Next steps:")
        print("="*80)
        print("1. Copy the lines above to your .env file")
        print("2. Test with: python3 -m sidekick.clients.mstodo lists")
        print("3. List your tasks: python3 -m sidekick.clients.mstodo tasks")

        print("\nAll done!\n")

    except KeyboardInterrupt:
        print("\n\nAborted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nError: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
