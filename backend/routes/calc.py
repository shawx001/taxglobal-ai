from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from backend.errors import error_response
from backend.schemas import (
    CryptoRequest,
    FederalIncomeRequest,
    FeieRequest,
    FicaRequest,
    NexusRequest,
    RsuRequest,
    SelfEmploymentRequest,
    StateIncomeRequest,
)
from engine import (
    crypto_gain_estimate,
    federal_income_tax,
    feie_estimate,
    fica_tax,
    nexus_estimate,
    rsu_tax_estimate,
    self_employment_tax,
    state_income_tax,
)

router = APIRouter()


def _request_id(request: Request) -> str:
    return str(request.state.request_id)


def _engine_response(request: Request, result: dict[str, Any]) -> dict[str, Any] | JSONResponse:
    if result.get("status") == "invalid_input":
        return JSONResponse(
            status_code=422,
            headers={"X-Request-ID": _request_id(request)},
            content=error_response(
                code="invalid_input",
                message=result.get("reason") or "Invalid input.",
                request_id=_request_id(request),
            ),
        )
    return result


def _call_engine(request: Request, fn: Callable[..., dict[str, Any]], **kwargs: Any) -> dict[str, Any] | JSONResponse:
    return _engine_response(request, fn(**kwargs))


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/calc/federal-income", response_model=None)
def calc_federal_income(payload: FederalIncomeRequest, request: Request) -> dict[str, Any] | JSONResponse:
    return _call_engine(request, federal_income_tax, **payload.model_dump())


@router.post("/calc/fica", response_model=None)
def calc_fica(payload: FicaRequest, request: Request) -> dict[str, Any] | JSONResponse:
    return _call_engine(request, fica_tax, **payload.model_dump())


@router.post("/calc/state-income", response_model=None)
def calc_state_income(payload: StateIncomeRequest, request: Request) -> dict[str, Any] | JSONResponse:
    return _call_engine(request, state_income_tax, **payload.model_dump())


@router.post("/calc/self-employment", response_model=None)
def calc_self_employment(payload: SelfEmploymentRequest, request: Request) -> dict[str, Any] | JSONResponse:
    return _call_engine(request, self_employment_tax, **payload.model_dump())


@router.post("/calc/feie", response_model=None)
def calc_feie(payload: FeieRequest, request: Request) -> dict[str, Any] | JSONResponse:
    return _call_engine(request, feie_estimate, **payload.model_dump())


@router.post("/calc/crypto", response_model=None)
def calc_crypto(payload: CryptoRequest, request: Request) -> dict[str, Any] | JSONResponse:
    data = payload.model_dump()
    data["method"] = data["method"].upper()
    return _call_engine(request, crypto_gain_estimate, **data)


@router.post("/calc/rsu", response_model=None)
def calc_rsu(payload: RsuRequest, request: Request) -> dict[str, Any] | JSONResponse:
    data = payload.model_dump()
    data["fair_market_value_per_share"] = data.pop("fmv_per_share")
    return _call_engine(request, rsu_tax_estimate, **data)


@router.post("/calc/nexus", response_model=None)
def calc_nexus(payload: NexusRequest, request: Request) -> dict[str, Any] | JSONResponse:
    return _call_engine(request, nexus_estimate, **payload.model_dump())
