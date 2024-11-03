from datetime import timezone
from typing import List, TypeAlias, Union

from dateutil.parser import parse as dateutil_parse
from fastapi import APIRouter, HTTPException, Path, Query, Request
from pydantic import Field as PydanticField
from pydantic import HttpUrl
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

PostsPaginationMetaWithExamples: TypeAlias = Annotated[
    PaginationMeta,
    PydanticField(
        description="ページネーション用情報。 リクエスト時に指定した offset / limit の値に応じて、次のページや前のページのリクエスト用 URL が設定される。",
        json_schema_extra={
            "examples": [
                {"next": "http://birdxplorer.onrender.com/api/v1/data/posts?offset=100&limit=100", "prev": "null"}
            ]
        },
    ),
]

NotesPaginationMetaWithExamples: TypeAlias = Annotated[
    PaginationMeta,
    PydanticField(
        description="ページネーション用情報。 リクエスト時に指定した offset / limit の値に応じて、次のページや前のページのリクエスト用 URL が設定される。",
        json_schema_extra={
            "examples": [
                {"next": "http://birdxplorer.onrender.com/api/v1/data/notes?offset=100&limit=100", "prev": "null"}
            ]
        },
    ),
]

TopicListWithExamples: TypeAlias = Annotated[
    List[Topic],
    PydanticField(
        description="推定されたトピックのリスト",
        json_schema_extra={
            "examples": [
                [
                    {"label": {"en": "Human rights", "ja": "人権"}, "referenceCount": 5566, "topicId": 28},
                    {"label": {"en": "Media", "ja": "メディア"}, "referenceCount": 3474, "topicId": 25},
                ]
            ]
        },
    ),
]

NoteListWithExamples: TypeAlias = Annotated[
    List[Note],
    PydanticField(
        description="コミュニティノートのリスト",
        json_schema_extra={
            "examples": [
                {
                    "noteId": "1845672983001710655",
                    "postId": "1842116937066955027",
                    "language": "ja",
                    "topics": [
                        {
                            "topicId": 26,
                            "label": {"ja": "セキュリティ上の脅威", "en": "security threat"},
                            "referenceCount": 0,
                        },
                        {"topicId": 47, "label": {"ja": "検閲", "en": "Censorship"}, "referenceCount": 0},
                        {"topicId": 51, "label": {"ja": "テクノロジー", "en": "technology"}, "referenceCount": 0},
                    ],
                    "summary": "Content Security Policyは情報の持ち出しを防止する仕組みではありません。コンテンツインジェクションの脆弱性のリスクを軽減する仕組みです。適切なContent Security Policyがレスポンスヘッダーに設定されている場合でも、外部への通信をブロックできない点に注意が必要です。    Content Security Policy Level 3  https://w3c.github.io/webappsec-csp/",  # noqa: E501
                    "currentStatus": "NEEDS_MORE_RATINGS",
                    "createdAt": 1728877704750,
                },
            ]
        },
    ),
]

PostListWithExamples: TypeAlias = Annotated[
    List[Post],
    PydanticField(
        description="X の Post のリスト",
        json_schema_extra={
            "examples": [
                {
                    "postId": "1846718284369912064",
                    "xUserId": "90954365",
                    "xUser": {
                        "userId": "90954365",
                        "name": "earthquakejapan",
                        "profileImage": "https://pbs.twimg.com/profile_images/1638600342/japan_rel96_normal.jpg",
                        "followersCount": 162934,
                        "followingCount": 6,
                    },
                    "text": "今後48時間以内に日本ではマグニチュード6.0の地震が発生する可能性があります。地図をご覧ください。（10月17日～10月18日） - https://t.co/nuyiVdM4FW https://t.co/Xd6U9XkpbL",  # noqa: E501
                    "mediaDetails": [
                        {
                            "mediaKey": "3_1846718279236177920-1846718284369912064",
                            "type": "photo",
                            "url": "https://pbs.twimg.com/media/GaDcfZoX0AAko2-.jpg",
                            "width": 900,
                            "height": 738,
                        }
                    ],
                    "createdAt": 1729094524000,
                    "likeCount": 451,
                    "repostCount": 104,
                    "impressionCount": 82378,
                    "links": [
                        {
                            "linkId": "9c139b99-8111-e4f0-ad41-fc9e40d08722",
                            "url": "https://www.quakeprediction.com/Earthquake%20Forecast%20Japan.html",
                        }
                    ],
                    "link": "https://x.com/earthquakejapan/status/1846718284369912064",
                },
            ]
        },
    ),
]


class TopicListResponse(BaseModel):
    data: TopicListWithExamples


class NoteListResponse(BaseModel):
    data: NoteListWithExamples
    meta: NotesPaginationMetaWithExamples


class PostListResponse(BaseModel):
    data: PostListWithExamples
    meta: PostsPaginationMetaWithExamples


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
        offset: int = Query(default=0, ge=0, **V1DataNotesDocs.params["offset"]),
        limit: int = Query(default=100, gt=0, le=1000, **V1DataNotesDocs.params["limit"]),
        topic_ids: Union[List[TopicId], None] = Query(default=None, **V1DataNotesDocs.params["topic_ids"]),
        post_ids: Union[List[PostId], None] = Query(default=None, **V1DataNotesDocs.params["post_ids"]),
        current_status: Union[None, List[str]] = Query(default=None, **V1DataNotesDocs.params["current_status"]),
        language: Union[LanguageIdentifier, None] = Query(default=None, **V1DataNotesDocs.params["language"]),
        search_text: Union[None, str] = Query(default=None, **V1DataPostsDocs.params["search_text"]),
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
                search_text=search_text,
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
            search_text=search_text,
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
        post_ids: Union[List[PostId], None] = Query(default=None),
        note_ids: Union[List[NoteId], None] = Query(default=None),
        created_at_from: Union[None, TwitterTimestamp, str] = Query(
            default=None, **V1DataPostsDocs.params["created_at_from"]
        ),
        created_at_to: Union[None, TwitterTimestamp, str] = Query(
            default=None, **V1DataPostsDocs.params["created_at_to"]
        ),
        offset: int = Query(default=0, ge=0, **V1DataPostsDocs.params["offset"]),
        limit: int = Query(default=100, gt=0, le=1000, **V1DataPostsDocs.params["limit"]),
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
                post_ids=post_ids,
                note_ids=note_ids,
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
            post_ids=post_ids,
            note_ids=note_ids,
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
