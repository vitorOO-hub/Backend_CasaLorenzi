"""Rota de saude, usada pelo healthcheck do deploy."""

from fastapi import APIRouter

router = APIRouter(tags=["saude"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
