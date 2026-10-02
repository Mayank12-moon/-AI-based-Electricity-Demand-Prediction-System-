"""
GridSense Delhi - Security, Authentication & RBAC Engine
Implements Argon2 password hashing, JWT access & refresh tokens,
and role-based access control (RBAC).
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db, SessionLocal
from app.models.models import User, AuditLog

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

# Password hashing using Argon2id with bcrypt fallback
pwd_context = CryptContext(schemes=["argon2", "bcrypt"], deprecated="auto")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login", auto_error=False)

# Roles hierarchy
ROLES = {
    "ADMIN": ["ADMIN", "SLDC_OPERATOR", "DISCOM_ANALYST", "VIEWER"],
    "SLDC_OPERATOR": ["SLDC_OPERATOR", "DISCOM_ANALYST", "VIEWER"],
    "DISCOM_ANALYST": ["DISCOM_ANALYST", "VIEWER"],
    "VIEWER": ["VIEWER"]
}


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(days=7))
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError:
        return None


def get_current_user(token: Optional[str] = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> Optional[User]:
    """Extract authenticated user from JWT token. Returns None if unauthenticated."""
    if not token:
        return None
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        return None
    username: Optional[str] = payload.get("sub")
    if not username:
        return None
    user = db.query(User).filter(User.username == username, User.is_active.is_(True)).first()
    return user


def require_auth(current_user: Optional[User] = Depends(get_current_user)) -> User:
    """Enforce authentication."""
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Provide Bearer token in Authorization header.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user


def require_role(allowed_roles: List[str]):
    """Enforce RBAC role permissions."""
    def _role_checker(current_user: User = Depends(require_auth)) -> User:
        if current_user.role not in allowed_roles and str(current_user.role) != "ADMIN":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Requires one of roles: {allowed_roles}. Current role: {current_user.role}"
            )
        return current_user
    return _role_checker


def seed_default_users_if_empty():
    """Seed initial role accounts if users table is empty."""
    db = SessionLocal()
    try:
        cnt = db.query(User).count()
        if cnt == 0:
            default_users = [
                {
                    "username": "admin",
                    "email": "admin@gridsense.delhi.gov.in",
                    "full_name": "GridSense Administrator",
                    "password": "GridSenseAdmin@2026",
                    "role": "ADMIN",
                    "discom_scope": None
                },
                {
                    "username": "sldc_operator",
                    "email": "controlroom@delhisldc.org",
                    "full_name": "Delhi SLDC Chief Dispatcher",
                    "password": "SLDCOperator@2026",
                    "role": "SLDC_OPERATOR",
                    "discom_scope": None
                },
                {
                    "username": "brpl_analyst",
                    "email": "analyst@bsesdelhi.com",
                    "full_name": "BSES Rajdhani Analyst",
                    "password": "BRPLAnalyst@2026",
                    "role": "DISCOM_ANALYST",
                    "discom_scope": "BRPL"
                },
                {
                    "username": "viewer",
                    "email": "guest@delhigrid.org",
                    "full_name": "Public Grid Viewer",
                    "password": "Viewer@2026",
                    "role": "VIEWER",
                    "discom_scope": None
                }
            ]
            for u in default_users:
                user = User(
                    username=u["username"],
                    email=u["email"],
                    full_name=u["full_name"],
                    hashed_password=get_password_hash(u["password"]),
                    role=u["role"],
                    discom_scope=u["discom_scope"],
                    is_active=True
                )
                db.add(user)
            db.commit()
            logger.info("[Security] Seeded 4 default operational users (admin, sldc_operator, brpl_analyst, viewer)")
    except Exception as e:
        db.rollback()
        logger.error(f"[Security] Failed seeding default users: {e}")
    finally:
        db.close()
