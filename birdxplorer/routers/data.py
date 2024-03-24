from typing import List, Union

from fastapi import APIRouter, Query

from ..models import BaseModel, ParticipantId, Post, PostId, Topic, UserEnrollment
from ..storage import Storage


class TopicListResponse(BaseModel):
    data: List[Topic]


class PostListResponse(BaseModel):
    data: List[Post]


def gen_router(storage: Storage) -> APIRouter:
    router = APIRouter()

    @router.get("/user-enrollments/{participant_id}", response_model=UserEnrollment)
    def get_user_enrollment_by_participant_id(participant_id: ParticipantId) -> UserEnrollment:
        res = storage.get_user_enrollment_by_participant_id(participant_id=participant_id)
        if res is None:
            raise ValueError(f"participant_id={participant_id} not found")
        return res

    @router.get("/topics", response_model=TopicListResponse)
    def get_topics() -> TopicListResponse:
        return TopicListResponse(data=list(storage.get_topics()))

    @router.get("/posts", response_model=PostListResponse)
    def get_posts(post_id: Union[List[PostId], None] = Query(default=None)) -> PostListResponse:
        if post_id is not None:
            return PostListResponse(data=list(storage.get_posts_by_ids(post_ids=post_id)))
        return PostListResponse(data=list(storage.get_posts()))

    return router
