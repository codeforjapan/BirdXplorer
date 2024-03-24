from datetime import timezone
from typing import List, Union

from dateutil.parser import parse as dateutil_parse
from fastapi import APIRouter, Query

from ..models import (
    BaseModel,
    ParticipantId,
    Post,
    PostId,
    Topic,
    TwitterTimestamp,
    UserEnrollment,
)
from ..storage import Storage


class TopicListResponse(BaseModel):
    data: List[Topic]


class PostListResponse(BaseModel):
    data: List[Post]


def str_to_twitter_timestamp(s: str) -> TwitterTimestamp:
    tmp = dateutil_parse(s)
    if tmp.tzinfo is None:
        tmp = tmp.replace(tzinfo=timezone.utc)
    return TwitterTimestamp.from_int(int(tmp.timestamp() * 1000))


def ensure_twitter_timestamp(t: Union[str, TwitterTimestamp]) -> TwitterTimestamp:
    return str_to_twitter_timestamp(t) if isinstance(t, str) else t


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
    def get_posts(
        post_id: Union[List[PostId], None] = Query(default=None),
        created_at_start: Union[None, str, TwitterTimestamp] = Query(default=None),
        created_at_end: Union[None, str, TwitterTimestamp] = Query(default=None),
    ) -> PostListResponse:
        if post_id is not None:
            return PostListResponse(data=list(storage.get_posts_by_ids(post_ids=post_id)))
        if created_at_start is not None:
            if created_at_end is not None:
                return PostListResponse(
                    data=list(
                        storage.get_posts_by_created_at_range(
                            start=ensure_twitter_timestamp(created_at_start),
                            end=ensure_twitter_timestamp(created_at_end),
                        )
                    )
                )
            return PostListResponse(
                data=list(storage.get_posts_by_created_at_start(start=ensure_twitter_timestamp(created_at_start)))
            )
        if created_at_end is not None:
            return PostListResponse(
                data=list(storage.get_posts_by_created_at_end(end=ensure_twitter_timestamp(created_at_end)))
            )
        return PostListResponse(data=list(storage.get_posts()))

    return router
