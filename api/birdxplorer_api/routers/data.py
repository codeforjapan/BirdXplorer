from datetime import timezone
from typing import List, TypeAlias, Union

from dateutil.parser import parse as dateutil_parse
from fastapi import APIRouter, HTTPException, Path, Query, Request
from pydantic import Field as PydanticField
from pydantic import HttpUrl
from pydantic_core import Url
from typing_extensions import Annotated

from birdxplorer_api.openapi_doc import (
    V1DataNotesDocs,
    V1DataPostsDocs,
    V1DataTopicsDocs,
    V1DataUserEnrollmentsDocs,
)
from birdxplorer_common.models import (
    BaseModel,
    LanguageIdentifier,
    NonNegativeInt,
    Note,
    NoteId,
    PaginationMeta,
    ParticipantId,
    Post,
    PostId,
    Topic,
    TopicId,
    TopicLabelString,
    TwitterTimestamp,
    UserEnrollment,
)
from birdxplorer_common.storage import Storage

PaginationMetaWithExamples: TypeAlias = Annotated[
    PaginationMeta,
    PydanticField(
        description="ページネーション用情報。 リクエスト時に指定した offset / limit の値に応じて、次のページや前のページのリクエスト用 URL が設定される。",
        examples=[
            # TODO: 公開エンドポイントの URL に差し替える
            PaginationMeta(next=Url("http://127.0.0.1:8000/api/v1/data/posts?offset=100&limit=100"), prev=None)
        ],
    ),
]

TopicListWithExamples: TypeAlias = Annotated[
    List[Topic],
    PydanticField(
        description="推定されたトピックのリスト",
        examples=[
            [
                # TODO: 実データの例に差し替える
                Topic(
                    topic_id=TopicId(1),
                    label={
                        LanguageIdentifier.EN: TopicLabelString("Technology"),
                        LanguageIdentifier.JA: TopicLabelString("テクノロジー"),
                    },
                    reference_count=NonNegativeInt(123),
                )
            ]
        ],
    ),
]

NoteListWithExamples: TypeAlias = Annotated[
    List[Note],
    PydanticField(
        description="コミュニティノートのリスト",
        examples=[
            [
                # TODO: 実データの例に差し替える
            ]
        ],
    ),
]

PostListWithExamples: TypeAlias = Annotated[
    List[Post],
    PydanticField(
        description="X の Post のリスト",
        examples=[
            [
                # TODO: 実データの例に差し替える
            ]
        ],
    ),
]


class TopicListResponse(BaseModel):
    data: TopicListWithExamples


class NoteListResponse(BaseModel):
    data: NoteListWithExamples
    meta: PaginationMeta


class PostListResponse(BaseModel):
    data: PostListWithExamples
    meta: PaginationMetaWithExamples


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

    @router.get(
        "/user-enrollments/{participant_id}",
        description=V1DataUserEnrollmentsDocs.description,
        response_model=UserEnrollment,
    )
    def get_user_enrollment_by_participant_id(
        participant_id: ParticipantId = Path(**V1DataUserEnrollmentsDocs.params["participant_id"]),
    ) -> UserEnrollment:
        res = storage.get_user_enrollment_by_participant_id(participant_id=participant_id)
        if res is None:
            raise ValueError(f"participant_id={participant_id} not found")
        return res

    @router.get("/topics", description=V1DataTopicsDocs.description, response_model=TopicListResponse)
    def get_topics() -> TopicListResponse:
        return TopicListResponse(data=list(storage.get_topics()))

    @router.get("/notes", description=V1DataNotesDocs.description, response_model=NoteListResponse)
    def get_notes(
        request: Request,
        note_ids: Union[List[NoteId], None] = Query(default=None, **V1DataNotesDocs.params["note_ids"]),
        created_at_from: Union[None, TwitterTimestamp] = Query(
            default=None, **V1DataNotesDocs.params["created_at_from"]
        ),
        created_at_to: Union[None, TwitterTimestamp] = Query(default=None, **V1DataNotesDocs.params["created_at_to"]),
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, gt=0, le=1000),
        topic_ids: Union[List[TopicId], None] = Query(default=None, **V1DataNotesDocs.params["topic_ids"]),
        post_ids: Union[List[PostId], None] = Query(default=None, **V1DataNotesDocs.params["post_ids"]),
        current_status: Union[None, List[str]] = Query(default=None, **V1DataNotesDocs.params["current_status"]),
        language: Union[LanguageIdentifier, None] = Query(default=None, **V1DataNotesDocs.params["language"]),
    ) -> NoteListResponse:
        if created_at_from is not None and isinstance(created_at_from, str):
            created_at_from = ensure_twitter_timestamp(created_at_from)
        if created_at_to is not None and isinstance(created_at_to, str):
            created_at_to = ensure_twitter_timestamp(created_at_to)

        notes = list(
            storage.get_notes(
                note_ids=note_ids,
                created_at_from=created_at_from,
                created_at_to=created_at_to,
                topic_ids=topic_ids,
                post_ids=post_ids,
                current_status=current_status,
                language=language,
                offset=offset,
                limit=limit,
            )
        )
        total_count = storage.get_number_of_notes(
            note_ids=note_ids,
            created_at_from=created_at_from,
            created_at_to=created_at_to,
            topic_ids=topic_ids,
            post_ids=post_ids,
            current_status=current_status,
            language=language,
        )

        baseurl = str(request.url).split("?")[0]
        next_offset = offset + limit
        prev_offset = max(offset - limit, 0)
        next_url = None
        if next_offset < total_count:
            next_url = f"{baseurl}?offset={next_offset}&limit={limit}"
        prev_url = None
        if offset > 0:
            prev_url = f"{baseurl}?offset={prev_offset}&limit={limit}"

        return NoteListResponse(data=notes, meta=PaginationMeta(next=next_url, prev=prev_url))

    @router.get("/posts", description=V1DataPostsDocs.description, response_model=PostListResponse)
    def get_posts(
        request: Request,
        post_id: Union[List[PostId], None] = Query(default=None, **V1DataPostsDocs.params["post_id"]),
        note_id: Union[List[NoteId], None] = Query(default=None, **V1DataPostsDocs.params["note_id"]),
        created_at_from: Union[None, TwitterTimestamp, str] = Query(
            default=None, **V1DataPostsDocs.params["created_at_from"]
        ),
        created_at_to: Union[None, TwitterTimestamp, str] = Query(
            default=None, **V1DataPostsDocs.params["created_at_to"]
        ),
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, gt=0, le=1000),
        search_text: Union[None, str] = Query(default=None, **V1DataPostsDocs.params["search_text"]),
        search_url: Union[None, HttpUrl] = Query(default=None, **V1DataPostsDocs.params["search_url"]),
        media: bool = Query(default=True, **V1DataPostsDocs.params["media"]),
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
