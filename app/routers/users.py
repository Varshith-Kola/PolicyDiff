"""User management and Google OAuth 2.0 authentication routes.

Provides:
  - Google OAuth login/callback flow (stateless — no session cookies)
  - User profile management
  - Follow/unfollow policies
  - Email notification preference management
  - GDPR compliance endpoints (data export, account deletion)
"""

import logging
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import User, UserPageFollow, EmailPreference, Policy
from app.schemas import (
    UserResponse,
    EmailPreferenceResponse,
    EmailPreferenceUpdate,
    FollowRequest,
    GDPRExportResponse,
    PolicyResponse,
)
from app.utils.security import generate_bearer_token
from app.utils.datetime_helpers import utcnow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["users"])

# Google OAuth endpoints
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

# In-memory nonce store for CSRF protection (maps state → True)
# In production with multiple workers, use Redis or DB instead
_pending_states: dict[str, bool] = {}


# ---------------------------------------------------------------------------
# Helper: resolve current user from bearer token
# ---------------------------------------------------------------------------

def _get_current_user(request: Request, db: Session) -> User:
    """Extract the current user from the request's auth token."""
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authentication token")

    token = auth_header[7:]
    settings = get_settings()
    from app.utils.security import verify_bearer_token
    user_id = verify_bearer_token(token, settings.secret_key)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found or deactivated")
    return user


def _build_user_response(user: User) -> UserResponse:
    """Build a UserResponse from a User ORM object."""
    prefs = None
    if user.email_preferences:
        prefs = EmailPreferenceResponse(
            email_enabled=user.email_preferences.email_enabled,
            frequency=user.email_preferences.frequency,
            severity_threshold=user.email_preferences.severity_threshold,
            unsubscribed_at=user.email_preferences.unsubscribed_at,
        )
    return UserResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        picture_url=user.picture_url,
        is_active=user.is_active,
        gdpr_consent_at=user.gdpr_consent_at,
        created_at=user.created_at,
        followed_policy_ids=[f.policy_id for f in user.followed_policies],
        email_preferences=prefs,
    )


# ---------------------------------------------------------------------------
# Google OAuth Flow
# ---------------------------------------------------------------------------

@router.get("/google/login")
async def google_login():
    """Redirect the user to Google's OAuth consent screen."""
    settings = get_settings()
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(status_code=501, detail="Google OAuth not configured")

    # Generate a CSRF state nonce and store it server-side
    state = secrets.token_urlsafe(24)
    _pending_states[state] = True
    # Keep the store bounded (max 100 pending states)
    if len(_pending_states) > 100:
        oldest = next(iter(_pending_states))
        _pending_states.pop(oldest, None)

    params = urlencode({
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "state": state,
        "prompt": "consent",
    })
    return RedirectResponse(url=f"{GOOGLE_AUTH_URL}?{params}")


@router.get("/google/callback")
async def google_callback(request: Request, db: Session = Depends(get_db)):
    """Handle Google's OAuth callback — create/update user and issue JWT.

    Uses a stateless approach: CSRF state is verified against an in-memory
    store (no session cookies required). After success, redirects to the
    frontend with the bearer token as a URL parameter.
    """
    settings = get_settings()
    code = request.query_params.get("code")
    state = request.query_params.get("state")

    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code from Google")

    # Verify CSRF state
    if not state or state not in _pending_states:
        logger.warning("OAuth callback with invalid or missing state parameter")
        raise HTTPException(status_code=400, detail="Invalid OAuth state — please try signing in again")
    _pending_states.pop(state, None)

    # Exchange authorization code for tokens
    try:
        async with httpx.AsyncClient() as client:
            token_resp = await client.post(GOOGLE_TOKEN_URL, data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
            })
            if token_resp.status_code != 200:
                logger.error(f"Google token exchange failed: {token_resp.text}")
                raise HTTPException(status_code=400, detail="Failed to exchange authorization code")
            token_data = token_resp.json()

            # Fetch user info using the access token
            userinfo_resp = await client.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {token_data['access_token']}"},
            )
            if userinfo_resp.status_code != 200:
                raise HTTPException(status_code=400, detail="Failed to fetch user info from Google")
            user_info = userinfo_resp.json()

    except httpx.HTTPError as e:
        logger.error(f"Google OAuth HTTP error: {e}")
        raise HTTPException(status_code=400, detail="OAuth authentication failed")

    google_id = user_info.get("sub")
    email = user_info.get("email")
    name = user_info.get("name")
    picture = user_info.get("picture")

    if not google_id or not email:
        raise HTTPException(status_code=400, detail="Missing required user information from Google")

    # Find or create user
    user = db.query(User).filter(User.google_id == google_id).first()
    now = utcnow()

    if user:
        # Update existing user
        user.email = email
        user.name = name
        user.picture_url = picture
        user.last_login_at = now
        user.updated_at = now
        logger.info(f"Existing user logged in: {email}")
    else:
        # Create new user with GDPR consent timestamp
        user = User(
            google_id=google_id,
            email=email,
            name=name,
            picture_url=picture,
            gdpr_consent_at=now,
            last_login_at=now,
        )
        db.add(user)
        db.flush()  # Get the user ID

        # Create default email preferences
        prefs = EmailPreference(
            user_id=user.id,
            email_enabled=True,
            frequency="immediate",
            severity_threshold="informational",
        )
        db.add(prefs)
        logger.info(f"New user registered: {email}")

    db.commit()
    db.refresh(user)

    # Issue our own bearer token
    bearer_token = generate_bearer_token(
        user_id=user.id,
        secret=settings.secret_key,
        expires_hours=168,  # 7 days for OAuth users
    )

    # Redirect to frontend with token
    return RedirectResponse(
        url=f"/?auth_token={bearer_token}&user_name={name or ''}"
    )


# ---------------------------------------------------------------------------
# User Profile
# ---------------------------------------------------------------------------

@router.get("/me", response_model=UserResponse)
def get_me(request: Request, db: Session = Depends(get_db)):
    """Get the currently authenticated user's profile."""
    user = _get_current_user(request, db)
    return _build_user_response(user)


# ---------------------------------------------------------------------------
# Follow / Unfollow Policies
# ---------------------------------------------------------------------------

@router.post("/me/follow")
def follow_policy(
    data: FollowRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Follow a policy to receive notifications about its changes."""
    user = _get_current_user(request, db)

    # Verify policy exists
    policy = db.query(Policy).filter(Policy.id == data.policy_id).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")

    # Check if already following
    existing = (
        db.query(UserPageFollow)
        .filter(UserPageFollow.user_id == user.id, UserPageFollow.policy_id == data.policy_id)
        .first()
    )
    if existing:
        return {"status": "already_following", "policy_id": data.policy_id}

    follow = UserPageFollow(user_id=user.id, policy_id=data.policy_id)
    db.add(follow)
    db.commit()
    logger.info(f"User {user.email} followed policy {data.policy_id}")
    return {"status": "followed", "policy_id": data.policy_id}


@router.delete("/me/follow/{policy_id}")
def unfollow_policy(
    policy_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Unfollow a policy to stop receiving its notifications."""
    user = _get_current_user(request, db)

    follow = (
        db.query(UserPageFollow)
        .filter(UserPageFollow.user_id == user.id, UserPageFollow.policy_id == policy_id)
        .first()
    )
    if not follow:
        raise HTTPException(status_code=404, detail="Not following this policy")

    db.delete(follow)
    db.commit()
    logger.info(f"User {user.email} unfollowed policy {policy_id}")
    return {"status": "unfollowed", "policy_id": policy_id}


@router.get("/me/following")
def get_following(request: Request, db: Session = Depends(get_db)):
    """Get all policies the current user is following."""
    user = _get_current_user(request, db)
    follows = (
        db.query(UserPageFollow)
        .filter(UserPageFollow.user_id == user.id)
        .all()
    )
    policy_ids = [f.policy_id for f in follows]
    policies = db.query(Policy).filter(Policy.id.in_(policy_ids)).all() if policy_ids else []
    return [
        {
            "id": p.id,
            "name": p.name,
            "company": p.company,
            "url": p.url,
            "policy_type": p.policy_type,
            "followed_at": next(
                (f.created_at for f in follows if f.policy_id == p.id), None
            ),
        }
        for p in policies
    ]


# ---------------------------------------------------------------------------
# Email Preferences
# ---------------------------------------------------------------------------

@router.get("/me/email-preferences", response_model=EmailPreferenceResponse)
def get_email_preferences(request: Request, db: Session = Depends(get_db)):
    """Get the current user's email notification preferences."""
    user = _get_current_user(request, db)
    prefs = db.query(EmailPreference).filter(EmailPreference.user_id == user.id).first()
    if not prefs:
        # Create default preferences
        prefs = EmailPreference(user_id=user.id)
        db.add(prefs)
        db.commit()
        db.refresh(prefs)
    return prefs


@router.put("/me/email-preferences", response_model=EmailPreferenceResponse)
def update_email_preferences(
    data: EmailPreferenceUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    """Update the current user's email notification preferences."""
    user = _get_current_user(request, db)
    prefs = db.query(EmailPreference).filter(EmailPreference.user_id == user.id).first()
    if not prefs:
        prefs = EmailPreference(user_id=user.id)
        db.add(prefs)

    if data.email_enabled is not None:
        prefs.email_enabled = data.email_enabled
        if not data.email_enabled:
            prefs.unsubscribed_at = utcnow()
        else:
            prefs.unsubscribed_at = None

    if data.frequency is not None:
        prefs.frequency = data.frequency

    if data.severity_threshold is not None:
        prefs.severity_threshold = data.severity_threshold

    db.commit()
    db.refresh(prefs)
    logger.info(f"User {user.email} updated email preferences")
    return prefs


@router.post("/me/unsubscribe")
def unsubscribe(request: Request, db: Session = Depends(get_db)):
    """One-click unsubscribe from all email notifications."""
    user = _get_current_user(request, db)
    prefs = db.query(EmailPreference).filter(EmailPreference.user_id == user.id).first()
    if not prefs:
        prefs = EmailPreference(user_id=user.id, email_enabled=False, unsubscribed_at=utcnow())
        db.add(prefs)
    else:
        prefs.email_enabled = False
        prefs.unsubscribed_at = utcnow()

    db.commit()
    logger.info(f"User {user.email} unsubscribed from email notifications")
    return {"status": "unsubscribed", "message": "You have been unsubscribed from all email notifications."}


# ---------------------------------------------------------------------------
# GDPR Compliance
# ---------------------------------------------------------------------------

@router.get("/me/export")
def export_user_data(request: Request, db: Session = Depends(get_db)):
    """Export all user data (GDPR Article 20 — right to data portability)."""
    user = _get_current_user(request, db)

    follows = (
        db.query(UserPageFollow)
        .filter(UserPageFollow.user_id == user.id)
        .all()
    )
    policy_ids = [f.policy_id for f in follows]
    policies = db.query(Policy).filter(Policy.id.in_(policy_ids)).all() if policy_ids else []

    return {
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "google_id": user.google_id,
            "created_at": str(user.created_at),
            "last_login_at": str(user.last_login_at) if user.last_login_at else None,
            "gdpr_consent_at": str(user.gdpr_consent_at) if user.gdpr_consent_at else None,
        },
        "followed_policies": [
            {"id": p.id, "name": p.name, "company": p.company, "url": p.url}
            for p in policies
        ],
        "email_preferences": {
            "email_enabled": user.email_preferences.email_enabled if user.email_preferences else True,
            "frequency": user.email_preferences.frequency if user.email_preferences else "immediate",
            "severity_threshold": user.email_preferences.severity_threshold if user.email_preferences else "informational",
        },
        "exported_at": str(utcnow()),
    }


@router.delete("/me/account")
def delete_account(request: Request, db: Session = Depends(get_db)):
    """Delete the user's account and all associated data (GDPR Article 17 — right to erasure)."""
    user = _get_current_user(request, db)
    email = user.email

    # Cascade delete handles follows + preferences
    db.delete(user)
    db.commit()

    logger.info(f"User account deleted (GDPR erasure): {email}")
    return {
        "status": "deleted",
        "message": "Your account and all associated data have been permanently deleted.",
    }
