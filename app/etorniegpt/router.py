from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.dependencies import get_current_user
from app.etorniegpt.countries import get_all_countries
from app.etorniegpt.schemas import EtornieGPTRequest, EtornieGPTResponse
from app.etorniegpt.service import ask_etorniegpt
from app.users.models import User

router = APIRouter(tags=["etorniegpt"])


@router.get("/countries")
async def list_countries(
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """Return list of countries with name and code for dropdowns."""
    countries = get_all_countries()
    return [
        {"country": c.get("country", ""), "country_code": c.get("country_code")}
        for c in countries
        if c.get("country")
    ]


@router.post("/etorniegpt", response_model=EtornieGPTResponse)
async def etorniegpt_endpoint(
    data: EtornieGPTRequest,
    current_user: User = Depends(get_current_user),
) -> EtornieGPTResponse:
    """Ask EtornieGPT an IP-related question."""
    try:
        result = await ask_etorniegpt(
            question=data.question,
            language=data.language,
        )
        return EtornieGPTResponse(**result)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"EtornieGPT service error: {exc}",
        ) from exc
