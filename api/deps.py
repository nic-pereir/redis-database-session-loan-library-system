from typing import Generator

import logging

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app import crud
from app.config import settings
from app.database import SessionLocal
from app.models import User
from core.security import decode_access_token

logger = logging.getLogger("app.session")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def session_log(message: str) -> None:
    """Log do ciclo de vida da Session (liga com DEBUG_SESSION_LOG=true no .env)."""
    if settings.DEBUG_SESSION_LOG:
        logger.info(message)


def get_db() -> Generator:
    """Uma Session por requisição: abre, entrega ao endpoint, e SEMPRE fecha."""
    db = SessionLocal()
    session_log("SESSION OPEN   (dependência get_db criou a Session)")
    try:
        yield db
    except Exception:
        # se o endpoint (ou o commit) levantou erro, desfaz o que ficou pendente
        db.rollback()
        session_log("SESSION ROLLBACK (erro durante a requisição)")
        raise
    finally:
        db.close()  # devolve a conexão ao pool
        session_log("SESSION CLOSE  (conexão devolvida ao pool)")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Não foi possível validar as credenciais.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise credentials_exception

    user = crud.get_user(db, user_id)
    if user is None:
        raise credentials_exception
    return user
