from fastapi import APIRouter, HTTPException

from app.schemas.node import (
    NodeListResponse,
    NodeStatusListResponse,
    NodeStatusResponse,
)
from app.services.cache_service import SimpleTTLCache
from app.services.node_inventory_service import NodeInventoryService
from app.services.node_status_service import NodeStatusService

router = APIRouter(prefix="/api/v1/nodes", tags=["nodes"])

cache = SimpleTTLCache()
inventory_service = NodeInventoryService(cache=cache)
status_service = NodeStatusService(cache=cache)


@router.get("", response_model=NodeListResponse)
def get_nodes() -> NodeListResponse:
    return inventory_service.get_node_list()


@router.get("/status", response_model=NodeStatusListResponse)
def get_all_nodes_status() -> NodeStatusListResponse:
    return status_service.get_all_node_status()


@router.get("/{node_name}/status", response_model=NodeStatusResponse)
def get_node_status(node_name: str) -> NodeStatusResponse:
    try:
        return status_service.get_node_status(node_name)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
