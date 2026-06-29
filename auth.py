# # auth.py
# import msal
# import os

# # ── Load from .env ─────────────────────────────────
# CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
# CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")

# # NTU uses "common" for multi-tenant, or use the NTU-specific tenant
# AUTHORITY = os.getenv("AZURE_AUTHORITY", "https://login.microsoftonline.com/common")

# # Redirect URI — change this to your deployed URL after deployment
# REDIRECT_PATH = "/auth/callback"
# # For local dev, this will be http://localhost:5050/auth/callback
# # For production, change to https://your-domain.com/auth/callback

# # def get_redirect_uri(request):
# #     """Build the full redirect URI based on the incoming request's host."""
# #     scheme = request.headers.get("X-Forwarded-Proto", request.scheme)
# #     host = request.headers.get("Host", request.host)
# #     return f"{scheme}://{host}{REDIRECT_PATH}"

# def get_redirect_uri(request):
#     # Use env var if set (production), otherwise build from request (local dev)
#     redirect_uri = os.getenv("REDIRECT_URI")
#     if redirect_uri:
#         return redirect_uri
#     scheme = request.headers.get("X-Forwarded-Proto", request.scheme)
#     host = request.headers.get("Host", request.host)
#     return f"{scheme}://{host}{REDIRECT_PATH}"


# def get_msal_app():
#     """Create and return a ConfidentialClientApplication instance."""
#     if not CLIENT_ID or not CLIENT_SECRET:
#         raise Exception("AZURE_CLIENT_ID and AZURE_CLIENT_SECRET must be set in .env")

#     return msal.ConfidentialClientApplication(
#         CLIENT_ID,
#         authority=AUTHORITY,
#         client_credential=CLIENT_SECRET,
#     )


# def get_auth_url(request):
#     """
#     Generate the Microsoft login URL that the frontend will redirect the user to.
#     """
#     app = get_msal_app()
#     redirect_uri = get_redirect_uri(request)

#     return app.get_authorization_request_url(
#         scopes=["User.Read"],
#         redirect_uri=redirect_uri,
#         prompt="select_account",  # Force account selection even if already signed in
#     )


# def get_token_from_code(request, auth_code):
#     """
#     Exchange the authorization code from Microsoft for an access token.
#     Returns the full token result dict.
#     """
#     app = get_msal_app()
#     redirect_uri = get_redirect_uri(request)

#     result = app.acquire_token_by_authorization_code(
#         auth_code,
#         scopes=["User.Read"],
#         redirect_uri=redirect_uri,
#     )

#     return result


# # def get_user_info(token_result):
# #     """
# #     Extract useful user info from the token result.
# #     Returns a dict with username, name, email, etc.
# #     """
# #     claims = token_result.get("id_token_claims", {})

# #     return {
# #         "username": claims.get("preferred_username", "unknown"),
# #         "name": claims.get("name", "unknown"),
# #         "email": claims.get("email", claims.get("preferred_username", "")),
# #         "oid": claims.get("oid", ""),  # Object ID — unique per user
# #         "tenant_id": claims.get("tid", ""),
# #     }

# def get_user_info(token_result):
#     claims = token_result.get("id_token_claims", {})
#     raw_username = claims.get("preferred_username", "unknown")
    
#     # Strip @domain if present → "U2312345G@student.main.ntu.edu.sg" → "U2312345G"
#     username = raw_username.split("@")[0] if "@" in raw_username else raw_username
    
#     # Get email — try to use a cleaner address for reminders
#     email = claims.get("email", claims.get("preferred_username", ""))
    
#     import re
    
#     # NTU subdomains → @ntu.edu.sg
#     # staff.main.ntu.edu.sg, student.main.ntu.edu.sg, assoc.main.ntu.edu.sg
#     if re.search(r"@(staff|student|assoc)\.main\.ntu\.edu\.sg$", email):
#         email = re.sub(r"@(staff|student|assoc)\.main\.ntu\.edu\.sg$", "@ntu.edu.sg", email)
    
#     return {
#         "username": username,
#         "name": claims.get("name", "unknown"),
#         "email": email,
#         "oid": claims.get("oid", ""),
#         "tenant_id": claims.get("tid", ""),
#     }

# auth.py
import msal
import os

# ── Load from .env ─────────────────────────────────
CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")

# NTU uses "common" for multi-tenant, or use the NTU-specific tenant
AUTHORITY = os.getenv("AZURE_AUTHORITY", "https://login.microsoftonline.com/common")

# Redirect URI — change this to your deployed URL after deployment
REDIRECT_PATH = "/auth/callback"
# For local dev, this will be http://localhost:5050/auth/callback
# For production, change to https://your-domain.com/auth/callback

# def get_redirect_uri(request):
#     """Build the full redirect URI based on the incoming request's host."""
#     scheme = request.headers.get("X-Forwarded-Proto", request.scheme)
#     host = request.headers.get("Host", request.host)
#     return f"{scheme}://{host}{REDIRECT_PATH}"

def get_redirect_uri(request):
    # Use env var if set (production), otherwise build from request (local dev)
    redirect_uri = os.getenv("REDIRECT_URI")
    if redirect_uri:
        return redirect_uri
    scheme = request.headers.get("X-Forwarded-Proto", request.scheme)
    host = request.headers.get("Host", request.host)
    return f"{scheme}://{host}{REDIRECT_PATH}"


def get_msal_app():
    """Create and return a ConfidentialClientApplication instance."""
    if not CLIENT_ID or not CLIENT_SECRET:
        raise Exception("AZURE_CLIENT_ID and AZURE_CLIENT_SECRET must be set in .env")

    return msal.ConfidentialClientApplication(
        CLIENT_ID,
        authority=AUTHORITY,
        client_credential=CLIENT_SECRET,
    )


def get_auth_url(request):
    """
    Generate the Microsoft login URL that the frontend will redirect the user to.
    """
    app = get_msal_app()
    redirect_uri = get_redirect_uri(request)

    return app.get_authorization_request_url(
        scopes=["User.Read"],
        redirect_uri=redirect_uri,
        prompt="select_account",  # Force account selection even if already signed in
    )


def get_token_from_code(request, auth_code):
    """
    Exchange the authorization code from Microsoft for an access token.
    Returns the full token result dict.
    """
    app = get_msal_app()
    redirect_uri = get_redirect_uri(request)

    result = app.acquire_token_by_authorization_code(
        auth_code,
        scopes=["User.Read"],
        redirect_uri=redirect_uri,
    )

    return result


# def get_user_info(token_result):
#     """
#     Extract useful user info from the token result.
#     Returns a dict with username, name, email, etc.
#     """
#     claims = token_result.get("id_token_claims", {})

#     return {
#         "username": claims.get("preferred_username", "unknown"),
#         "name": claims.get("name", "unknown"),
#         "email": claims.get("email", claims.get("preferred_username", "")),
#         "oid": claims.get("oid", ""),  # Object ID — unique per user
#         "tenant_id": claims.get("tid", ""),
#     }

def get_user_info(token_result):
    claims = token_result.get("id_token_claims", {})
    raw_username = claims.get("preferred_username", "unknown")
    
    # Strip @domain if present → "U2312345G@student.main.ntu.edu.sg" → "U2312345G"
    username = raw_username.split("@")[0] if "@" in raw_username else raw_username
    
    # Get email — try to use a cleaner address for reminders
    email = claims.get("email", claims.get("preferred_username", ""))
    
    import re
    
    # NTU subdomains → @ntu.edu.sg
    # staff.main.ntu.edu.sg, student.main.ntu.edu.sg, assoc.main.ntu.edu.sg
    if re.search(r"@(staff|student|assoc)\.main\.ntu\.edu\.sg$", email):
        email = re.sub(r"@(staff|student|assoc)\.main\.ntu\.edu\.sg$", "@ntu.edu.sg", email)
    
    return {
        "username": username,
        "name": claims.get("name", "unknown"),
        "email": email,
        "oid": claims.get("oid", ""),
        "tenant_id": claims.get("tid", ""),
    }