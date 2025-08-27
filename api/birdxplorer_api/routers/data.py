from datetime import timezone
from typing import Any, Dict, List, TypeAlias, Union
from urllib.parse import parse_qs as parse_query_string
from urllib.parse import urlencode

from dateutil.parser import parse as dateutil_parse
from fastapi import APIRouter, HTTPException, Path, Query, Request
from pydantic import Field as PydanticField
from pydantic import HttpUrl
from typing_extensions import Annotated

from birdxplorer_api.openapi_doc import (
    V1DataNotesDocs,
    V1DataPostsDocs,
    V1DataSearchDocs,
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
    SummaryString,
    Topic,
    TopicId,
    TwitterTimestamp,
    UserEnrollment,
    UserId,
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

SearchPaginationMetaWithExamples: TypeAlias = Annotated[
    PaginationMeta,
    PydanticField(
        description="ページネーション用情報。 リクエスト時に指定した offset / limit の値に応じて、次のページや前のページのリクエスト用 URL が設定される。",
        json_schema_extra={
            "examples": [
                {"next": "http://birdxplorer.onrender.com/api/v1/data/search?offset=100&limit=100", "prev": "null"}
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
                    "hasBeenHelpfuled": False,
                    "helpfulCount": 0,
                    "notHelpfulCount": 2,
                    "somewhatHelpfulCount": 1,
                    "currentStatusHistory": [{"status": "NEEDS_MORE_RATINGS", "date": 1728877704750}],
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


class SearchedNote(BaseModel):
    note_id: Annotated[NoteId, PydanticField(description="コミュニティノートのID")]
    summary: Annotated[SummaryString, PydanticField(description="コミュニティノートの本文")]
    language: Annotated[LanguageIdentifier, PydanticField(description="コミュニティノートの言語")]
    topics: Annotated[List[Topic], PydanticField(description="コミュニティノートに関連付けられたトピックのリスト")]
    post_id: Annotated[PostId, PydanticField(description="関連するPostのID")]
    current_status: Annotated[
        Annotated[
            str,
            PydanticField(
                json_schema_extra={
                    "enum": ["NEEDS_MORE_RATINGS", "CURRENTLY_RATED_HELPFUL", "CURRENTLY_RATED_NOT_HELPFUL"]
                },
            ),
        ]
        | None,
        PydanticField(
            description="コミュニティノートの現在の評価状態",
        ),
    ]
    created_at: Annotated[
        TwitterTimestamp, PydanticField(description="コミュニティノートの作成日時 (ミリ秒単位の UNIX EPOCH TIMESTAMP)")
    ]
    # New helpful rating fields
    has_been_helpfuled: Annotated[bool, PydanticField(description="ノートが役立つと評価されたことがあるかどうか")]
    helpful_count: Annotated[int, PydanticField(description="役立つ評価の数")]
    not_helpful_count: Annotated[int, PydanticField(description="役立たない評価の数")]
    somewhat_helpful_count: Annotated[int, PydanticField(description="やや役立つ評価の数")]
    current_status_history: Annotated[List[Dict[str, Any]], PydanticField(description="ステータス変更履歴")]
    post: Annotated[Post, PydanticField(description="コミュニティノートに関連付けられた Post の情報")]


SearchWithExamples: TypeAlias = Annotated[
    List[SearchedNote],
    PydanticField(
        description="検索結果のノートのリスト",
        json_schema_extra={
            "examples": [
                {
                    "noteId": "1845672983001710655",
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
                    "hasBeenHelpfuled": False,
                    "helpfulCount": 0,
                    "notHelpfulCount": 2,
                    "somewhatHelpfulCount": 1,
                    "currentStatusHistory": [{"status": "NEEDS_MORE_RATINGS", "date": 1728877704750}],
                    "post": {
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


class SearchResponse(BaseModel):
    data: SearchWithExamples
    meta: SearchPaginationMetaWithExamples


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
    try:
        timestamp = str_to_twitter_timestamp(t) if isinstance(t, str) else t
        return timestamp
    except OverflowError:
        raise OverflowError("Timestamp out of range")


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
        search_text: Union[None, str] = Query(default=None, **V1DataNotesDocs.params["search_text"]),
    ) -> NoteListResponse:
        try:
            if created_at_from is not None and isinstance(created_at_from, str):
                created_at_from = ensure_twitter_timestamp(created_at_from)
            if created_at_to is not None and isinstance(created_at_to, str):
                created_at_to = ensure_twitter_timestamp(created_at_to)
        except OverflowError as e:
            raise HTTPException(status_code=422, detail=str(e))

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
        user_ids: Union[List[UserId], None] = Query(default=None),
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
        try:
            if created_at_from is not None and isinstance(created_at_from, str):
                created_at_from = ensure_twitter_timestamp(created_at_from)
            if created_at_to is not None and isinstance(created_at_to, str):
                created_at_to = ensure_twitter_timestamp(created_at_to)
        except OverflowError as e:
            raise HTTPException(status_code=422, detail=str(e))

        posts = list(
            storage.get_posts(
                post_ids=post_ids,
                note_ids=note_ids,
                user_ids=user_ids,
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
            user_ids=user_ids,
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

    @router.get("/search", description=V1DataSearchDocs.description, response_model=SearchResponse)
    def search(
        request: Request,
        note_includes_text: Union[None, str] = Query(default=None, **V1DataSearchDocs.params["note_includes_text"]),
        note_excludes_text: Union[None, str] = Query(default=None, **V1DataSearchDocs.params["note_excludes_text"]),
        post_includes_text: Union[None, str] = Query(default=None, **V1DataSearchDocs.params["post_includes_text"]),
        post_excludes_text: Union[None, str] = Query(default=None, **V1DataSearchDocs.params["post_excludes_text"]),
        language: Union[LanguageIdentifier, None] = Query(default=None, **V1DataSearchDocs.params["language"]),
        topic_ids: Union[List[TopicId], None] = Query(default=None, **V1DataSearchDocs.params["topic_ids"]),
        note_status: Union[None, List[str]] = Query(default=None, **V1DataSearchDocs.params["note_status"]),
        note_created_at_from: Union[None, TwitterTimestamp, str] = Query(
            default=None, **V1DataSearchDocs.params["note_created_at_from"]
        ),
        note_created_at_to: Union[None, TwitterTimestamp, str] = Query(
            default=None, **V1DataSearchDocs.params["note_created_at_to"]
        ),
        x_user_names: Union[List[str], None] = Query(default=None, **V1DataSearchDocs.params["x_user_name"]),
        x_user_followers_count_from: Union[None, int] = Query(
            default=None, **V1DataSearchDocs.params["x_user_followers_count_from"]
        ),
        x_user_follow_count_from: Union[None, int] = Query(
            default=None, **V1DataSearchDocs.params["x_user_follow_count_from"]
        ),
        post_like_count_from: Union[None, int] = Query(default=None, **V1DataSearchDocs.params["post_like_count_from"]),
        post_repost_count_from: Union[None, int] = Query(
            default=None, **V1DataSearchDocs.params["post_repost_count_from"]
        ),
        post_impression_count_from: Union[None, int] = Query(
            default=None, **V1DataSearchDocs.params["post_impression_count_from"]
        ),
        post_includes_media: bool = Query(default=True, **V1DataSearchDocs.params["post_includes_media"]),
        offset: int = Query(default=0, ge=0, **V1DataSearchDocs.params["offset"]),
        limit: int = Query(default=100, gt=0, le=1000, **V1DataSearchDocs.params["limit"]),
    ) -> SearchResponse:
        # Convert timestamp strings to TwitterTimestamp objects
        try:
            if note_created_at_from is not None and isinstance(note_created_at_from, str):
                note_created_at_from = ensure_twitter_timestamp(note_created_at_from)
            if note_created_at_to is not None and isinstance(note_created_at_to, str):
                note_created_at_to = ensure_twitter_timestamp(note_created_at_to)
        except OverflowError as e:
            raise HTTPException(status_code=422, detail=str(e))

        # Get search results using the optimized storage method
        results = []
        for note, post in storage.search_notes_with_posts(
            note_includes_text=note_includes_text,
            note_excludes_text=note_excludes_text,
            post_includes_text=post_includes_text,
            post_excludes_text=post_excludes_text,
            language=language,
            topic_ids=topic_ids,
            note_status=note_status,
            note_created_at_from=note_created_at_from,
            note_created_at_to=note_created_at_to,
            x_user_names=x_user_names,
            x_user_followers_count_from=x_user_followers_count_from,
            x_user_follow_count_from=x_user_follow_count_from,
            post_like_count_from=post_like_count_from,
            post_repost_count_from=post_repost_count_from,
            post_impression_count_from=post_impression_count_from,
            post_includes_media=post_includes_media,
            offset=offset,
            limit=limit,
        ):
            results.append(
                SearchedNote(
                    note_id=note.note_id,
                    language=note.language,
                    topics=note.topics,
                    post_id=note.post_id,
                    summary=note.summary,
                    current_status=note.current_status,
                    created_at=note.created_at,
                    has_been_helpfuled=note.has_been_helpfuled,
                    helpful_count=note.helpful_count,
                    not_helpful_count=note.not_helpful_count,
                    somewhat_helpful_count=note.somewhat_helpful_count,
                    current_status_history=[
                        {"status": history.status, "date": history.date} for history in note.current_status_history
                    ],
                    post=post,
                )
            )
        # Get total count for pagination
        total_count = storage.count_search_results(
            note_includes_text=note_includes_text,
            note_excludes_text=note_excludes_text,
            post_includes_text=post_includes_text,
            post_excludes_text=post_excludes_text,
            language=language,
            topic_ids=topic_ids,
            note_status=note_status,
            note_created_at_from=note_created_at_from,
            note_created_at_to=note_created_at_to,
            x_user_names=x_user_names,
            x_user_followers_count_from=x_user_followers_count_from,
            x_user_follow_count_from=x_user_follow_count_from,
            post_like_count_from=post_like_count_from,
            post_repost_count_from=post_repost_count_from,
            post_impression_count_from=post_impression_count_from,
            post_includes_media=post_includes_media,
        )

        # Generate pagination URLs
        base_url = str(request.url).split("?")[0]
        raw_query = request.url.query
        query_params = parse_query_string(raw_query)
        next_offset = offset + limit
        prev_offset = max(offset - limit, 0)

        next_url = None
        if next_offset < total_count:
            query_params["offset"] = [str(next_offset)]
            query_params["limit"] = [str(limit)]
            next_url = f"{base_url}?{urlencode(query_params, doseq=True)}"

        prev_url = None
        if offset > 0:
            query_params["offset"] = [str(prev_offset)]
            query_params["limit"] = [str(limit)]
            prev_url = f"{base_url}?{urlencode(query_params, doseq=True)}"

        return SearchResponse(data=results, meta=PaginationMeta(next=next_url, prev=prev_url))

    return router
