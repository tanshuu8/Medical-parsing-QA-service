"""API v1 router registry consolidating all endpoint subrouters."""
from fastapi import APIRouter
from app.api.v1.endpoints import documents, nodes, selections, generations

api_router = APIRouter()

api_router.include_router(documents.router, prefix="/documents", tags=["documents"])
api_router.include_router(nodes.router, prefix="/nodes", tags=["nodes"])
api_router.include_router(selections.router, prefix="/selection", tags=["selections"])
api_router.include_router(generations.router, prefix="/generations", tags=["generations"])
