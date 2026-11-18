from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.deps import auth_rate_limit, current_user_id, get_db, require_auth
from app.routers import no_content
from app.schemas import (
    AuthUserDto,
    ChangePasswordBody,
    LoginBody,
    LoginResultDto,
    RequestRecoveryBody,
    ResetPasswordBody,
    VerifyRecoveryBody,
)
from app.services import auth as service
from app.state import get_email_sender

router = APIRouter(prefix="/api/auth", tags=["Auth"])
limited = [Depends(auth_rate_limit)]


@router.post("/login", response_model=LoginResultDto, dependencies=limited)
def login(body: LoginBody, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    return service.login(db, settings, body)


@router.get("/me", response_model=AuthUserDto, dependencies=[Depends(require_auth)])
def me(db: Session = Depends(get_db), user_id=Depends(current_user_id)):
    return service.get_current_user(db, user_id)


@router.put("/change-password", status_code=204, dependencies=[Depends(require_auth)])
def change_password(body: ChangePasswordBody, db: Session = Depends(get_db), user_id=Depends(current_user_id)):
    service.change_password(db, user_id, body)
    return no_content()


@router.post("/password-recovery", status_code=204, dependencies=limited)
def request_recovery(body: RequestRecoveryBody, db: Session = Depends(get_db)):
    """Envía un código de 6 dígitos al correo. Responde igual exista o no la cuenta."""
    service.request_recovery(db, get_email_sender(), body)
    return no_content()


@router.post("/password-recovery/verify", status_code=204, dependencies=limited)
def verify_recovery(body: VerifyRecoveryBody, db: Session = Depends(get_db)):
    service.verify_recovery_code(db, body)
    return no_content()


@router.post("/password-recovery/reset", status_code=204, dependencies=limited)
def reset_password(body: ResetPasswordBody, db: Session = Depends(get_db)):
    service.reset_password(db, body)
    return no_content()
