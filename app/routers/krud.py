from fastapi import APIRouter, Depends, Response

from app.deps import require_auth
from app.security import Principal
from app.state import get_krud_signer

router = APIRouter(prefix="/api/krud", tags=["Krud"], dependencies=[Depends(require_auth)])


@router.get("/asercion")
def assertion(principal: Principal = Depends(require_auth)):
    """Firmador de KRUD: el kit lo llama antes de cada ticket con el token de la sesión."""
    signer = get_krud_signer()
    if not signer.enabled:
        return Response(status_code=404)
    return Response(
        content=signer.sign(principal),
        media_type="text/plain",
        headers={"Cache-Control": "no-store"},
    )
