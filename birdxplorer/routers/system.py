from fastapi import APIRouter

from ..models import Message


def gen_router() -> APIRouter:
    router = APIRouter()

    @router.get("/ping", response_model=Message)
    async def ping() -> Message:
        return Message(message="pong")

    return router
