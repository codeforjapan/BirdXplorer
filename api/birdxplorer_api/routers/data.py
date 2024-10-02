from datetime import timezone
from typing import List, Union

from dateutil.parser import parse as dateutil_parse
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import HttpUrl

from birdxplorer_common.models import (
    BaseModel,
    LanguageIdentifier,
    Note,
    NoteId,
    PaginationMeta,
    ParticipantId,
    Post,
    PostId,
    Topic,
    TopicId,
    TwitterTimestamp,
    UserEnrollment,
)
from birdxplorer_common.storage import Storage


class TopicListResponse(BaseModel):
    data: List[Topic]


class NoteListResponse(BaseModel):
    data: List[Note]


class PostListResponse(BaseModel):
    data: List[Post]
    meta: PaginationMeta


def str_to_twitter_timestamp(s: str) -> TwitterTimestamp:
    try:
        return TwitterTimestamp.from_int(int(s))
    except ValueError:
        pass
    try:
        tmp = dateutil_parse(s)
        if tmp.tzinfo is None:
            tmp = tmp.replace(tzinfo=timezone.utc)
        return TwitterTimestamp.from_int(int(tmp.timestamp() * 1000))
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid TwitterTimestamp string: {s}")


def ensure_twitter_timestamp(t: Union[str, TwitterTimestamp]) -> TwitterTimestamp:
    return str_to_twitter_timestamp(t) if isinstance(t, str) else t


def gen_router(storage: Storage) -> APIRouter:
    router = APIRouter()

    @router.get("/user-enrollments/{participant_id}", response_model=UserEnrollment)
    def get_user_enrollment_by_participant_id(
        participant_id: ParticipantId,
    ) -> UserEnrollment:
        res = storage.get_user_enrollment_by_participant_id(participant_id=participant_id)
        if res is None:
            raise ValueError(f"participant_id={participant_id} not found")
        return res

    @router.get("/topics", response_model=TopicListResponse)
    def get_topics() -> TopicListResponse:
        return TopicListResponse(data=list(storage.get_topics()))

    @router.get("/notes", response_model=NoteListResponse)
    def get_notes(
        note_ids: Union[List[NoteId], None] = Query(default=None),
        created_at_from: Union[None, TwitterTimestamp] = Query(default=None),
        created_at_to: Union[None, TwitterTimestamp] = Query(default=None),
        topic_ids: Union[List[TopicId], None] = Query(default=None),
        post_ids: Union[List[PostId], None] = Query(default=None),
        current_status: Union[None, List[str]] = Query(default=None),
        language: Union[LanguageIdentifier, None] = Query(default=None),
    ) -> NoteListResponse:
        return NoteListResponse(
            data=list(
                storage.get_notes(
                    note_ids=note_ids,
                    created_at_from=created_at_from,
                    created_at_to=created_at_to,
                    topic_ids=topic_ids,
                    post_ids=post_ids,
                    current_status=current_status,
                    language=language,
                )
            )
        )

    @router.get("/posts", response_model=PostListResponse)
    def get_posts(
        request: Request,
        post_id: Union[List[PostId], None] = Query(default=None),
        note_id: Union[List[NoteId], None] = Query(default=None),
        created_at_from: Union[None, TwitterTimestamp, str] = Query(default=None),
        created_at_to: Union[None, TwitterTimestamp, str] = Query(default=None),
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, gt=0, le=1000),
        search_text: Union[None, str] = Query(default=None),
        search_url: Union[None, HttpUrl] = Query(default=None),
        media: bool = Query(default=True),
    ) -> PostListResponse:
        if created_at_from is not None and isinstance(created_at_from, str):
            created_at_from = ensure_twitter_timestamp(created_at_from)
        if created_at_to is not None and isinstance(created_at_to, str):
            created_at_to = ensure_twitter_timestamp(created_at_to)
        posts = list(
            storage.get_posts(
                post_ids=post_id,
                note_ids=note_id,
                start=created_at_from,
                end=created_at_to,
                search_text=search_text,
                search_url=search_url,
                offset=offset,
                limit=limit,
                with_media=media,
            )
        )
        total_count = storage.get_number_of_posts(
            post_ids=post_id,
            note_ids=note_id,
            start=created_at_from,
            end=created_at_to,
            search_text=search_text,
            search_url=search_url,
        )

        base_url = str(request.url).split("?")[0]
        next_offset = offset + limit
        prev_offset = max(offset - limit, 0)
        next_url = None
        if next_offset < total_count:
            next_url = f"{base_url}?offset={next_offset}&limit={limit}"
        prev_url = None
        if offset > 0:
            prev_url = f"{base_url}?offset={prev_offset}&limit={limit}"

        return PostListResponse(data=posts, meta=PaginationMeta(next=next_url, prev=prev_url))

    return router
