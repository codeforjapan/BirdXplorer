from dataclasses import dataclass
from typing import Dict, Generic

from fastapi.openapi.models import Example
from typing_extensions import LiteralString, TypedDict, TypeVar

from birdxplorer_common.models import LanguageIdentifier, NoteId, PostId


class FastAPIEndpointQueryDocsRequired(TypedDict):
    description: str


class FastAPIEndpointParamDocs(FastAPIEndpointQueryDocsRequired, total=False):
    openapi_examples: Dict[str, Example]


_KEY = TypeVar("_KEY", bound=LiteralString)


@dataclass
class FastAPIEndpointDocs(Generic[_KEY]):
    """
    FastAPI のエンドポイントのドキュメントをまとめた dataclass。
    """

    description: str
    params: Dict[_KEY, FastAPIEndpointParamDocs]


SAMPLE_POST_IDS = [PostId("1828261879854309500"), PostId("1828261879854309501")]
SAMPLE_NOTE_IDS = [NoteId("1845672983001710655"), NoteId("1845776988935770187")]

v1_data_posts_post_id: FastAPIEndpointParamDocs = {
    "description": """
データを取得する X の Post の ID。

複数回クエリパラメータを指定する / カンマ区切りで複数の ID を指定することで複数の Post 一括で取得できる。

---

なお、Post の ID は Post の URL から確認できる。

| Post の URL                                           | Post の ID          |
| :---------------------------------------------------: | :-----------------: |
| https://x.com/CodeforJapan/status/1828261879854309500 | 1828261879854309500 |
""",
    "openapi_examples": {
        "default": {
            "summary": "指定しない (デフォルト)",
            "value": None,
        },
        "single": {
            "summary": "Post を 1つ取得する",
            "value": [SAMPLE_POST_IDS[0]],
        },
        "multiple_query": {
            "summary": "Post を複数取得する (クエリパラメータ)",
            "value": SAMPLE_POST_IDS,
        },
        "multiple_comma": {
            "summary": "Post を複数取得する (カンマ区切り)",
            "value": [",".join(SAMPLE_POST_IDS)],
        },
    },
}

v1_data_posts_note_id: FastAPIEndpointParamDocs = {
    "description": """
Post のデータ取得に利用する X のコミュニティノートの ID。
コミュニティノートと Post は 1 : 1 で紐づいている。

複数回クエリパラメータを指定する / カンマ区切りで複数の ID を指定することで複数の Post を一括で取得できる。
""",
    "openapi_examples": {
        "default": {
            "summary": "指定しない (デフォルト)",
            "value": None,
        },
        "single": {
            "summary": "コミュニティノートに紐づいた Post を 1つ取得する",
            "value": [SAMPLE_NOTE_IDS[0]],
        },
        "multiple_query": {
            "summary": "複数のコミュニティノートについて、それぞれに紐づいた Post を取得する (クエリパラメータ)",
            "value": SAMPLE_NOTE_IDS,
        },
        "multiple_comma": {
            "summary": "複数のコミュニティノートについて、それぞれに紐づいた Post を取得する (カンマ区切り)",
            "value": [",".join(SAMPLE_NOTE_IDS)],
        },
    },
}

v1_data_posts_created_at_from: FastAPIEndpointParamDocs = {
    "description": """
取得する Post の作成日時の下限。**指定した日時と同時かそれより新しい** Post のみを取得する。

指定する形式は UNIX EPOCH TIME (ミリ秒) 。
""",
    "openapi_examples": {
        "default": {
            "summary": "指定しない (デフォルト)",
            "value": None,
        },
        "normal": {
            "summary": "2024 / 1 / 1 00:00 (JST) 以降の Post を取得する",
            "value": 1704034800000,
        },
    },
}

v1_data_posts_created_at_to: FastAPIEndpointParamDocs = {
    "description": """
取得する Post の作成日時の上限。**指定した日時よりも古い** Post のみを取得する。

指定する形式は UNIX EPOCH TIME (ミリ秒) 。
""",
    "openapi_examples": {
        "default": {
            "summary": "指定しない (デフォルト)",
            "value": None,
        },
        "normal": {
            "summary": "2024 / 7 / 1 00:00 (JST) より前の Post を取得する",
            "value": 1719759600000,
        },
    },
}

v1_data_posts_offset: FastAPIEndpointParamDocs = {
    "description": """
取得する Post のリストの先頭からのオフセット。ページネーションに利用される。


ただし、レスポンスの `meta.next` や `meta.prev` で次のページや前のページのリクエスト用 URL が提供されるため、
そちらを利用したほうが良い場合もある。
""",
    "openapi_examples": {
        "default": {
            "summary": "0 (デフォルト)",
            "value": 0,
        },
        "offset_100": {
            "summary": "100",
            "value": 100,
        },
    },
}

v1_data_posts_limit: FastAPIEndpointParamDocs = {
    "description": """
取得する Post のリストの最大数。 0 ～ 1000 まで指定できる。ページネーションに利用される。


ただし、 `meta.next` や `meta.prev` で次のページや前のページのリクエスト用 URL が提供されるため、
そちらを利用したほうが良い場合もある。
""",
    "openapi_examples": {
        "default": {
            "summary": "100 (デフォルト)",
            "value": 100,
        },
        "limit_50": {
            "summary": "50",
            "value": 50,
        },
    },
}

v1_data_posts_search_text: FastAPIEndpointParamDocs = {
    "description": """
指定した文字列を含む Post を検索して取得する。検索は Post の**本文に対して**行われる。
""",
    "openapi_examples": {
        "default": {
            "summary": "指定しない (デフォルト)",
            "value": None,
        },
        "python": {
            "summary": "「Python」を含む Post を取得する",
            "value": "Python",
        },
    },
}

v1_data_posts_search_url: FastAPIEndpointParamDocs = {
    "description": """
指定した URL を含む Post を検索して取得する。
""",
    "openapi_examples": {
        "default": {
            "summary": "指定しない (デフォルト)",
            "value": None,
        },
        "example.com": {
            "summary": "「https://example.com」を含む Post を取得する",
            "value": "https://example.com",
        },
    },
}

v1_data_posts_media: FastAPIEndpointParamDocs = {
    "description": """
Post に紐づいた画像や動画などのメディア情報を取得するかどうか。

必要に応じて `false` に設定することでメディア情報を取得しないようにできる。
""",
    "openapi_examples": {
        "default": {
            "summary": "メディア情報を取得する (デフォルト)",
            "value": True,
        },
        "no_media": {
            "summary": "メディア情報を取得しない",
            "value": False,
        },
    },
}

V1DataPostsDocs = FastAPIEndpointDocs(
    "Post のデータを取得するエンドポイント",
    {
        "post_id": v1_data_posts_post_id,
        "note_id": v1_data_posts_note_id,
        "created_at_from": v1_data_posts_created_at_from,
        "created_at_to": v1_data_posts_created_at_to,
        "offset": v1_data_posts_offset,
        "limit": v1_data_posts_limit,
        "search_text": v1_data_posts_search_text,
        "search_url": v1_data_posts_search_url,
        "media": v1_data_posts_media,
    },
)

v1_data_notes_note_ids: FastAPIEndpointParamDocs = {
    "description": """
データを取得する X のコミュニティノートの ID。

複数回クエリパラメータを指定する / カンマ区切りで複数の ID を指定することで複数のコミュニティノートを一括で取得できる。
""",
    "openapi_examples": {
        "default": {
            "summary": "指定しない (デフォルト)",
            "value": None,
        },
        "single": {
            "summary": "コミュニティノートを 1つ取得する",
            "value": [SAMPLE_NOTE_IDS[0]],
        },
        "multiple_query": {
            "summary": "コミュニティノートを複数取得する (クエリパラメータ)",
            "value": SAMPLE_NOTE_IDS,
        },
        "multiple_comma": {
            "summary": "コミュニティノートを複数取得する (カンマ区切り)",
            "value": [",".join(SAMPLE_NOTE_IDS)],
        },
    },
}

v1_data_notes_created_at_from: FastAPIEndpointParamDocs = {
    "description": """
取得するコミュニティノートの作成日時の下限。**指定した日時と同時かそれより新しい**コミュニティノートのみを取得する。

指定する形式は UNIX EPOCH TIME (ミリ秒) 。
""",
    "openapi_examples": {
        "default": {
            "summary": "指定しない (デフォルト)",
            "value": None,
        },
        "normal": {
            "summary": "2024 / 1 / 1 00:00 (JST) 以降のコミュニティノートを取得する",
            "value": 1704034800000,
        },
    },
}

v1_data_notes_created_at_to: FastAPIEndpointParamDocs = {
    "description": """
取得するコミュニティノートの作成日時の上限。**指定した日時よりも古い**コミュニティノートのみを取得する。

指定する形式は UNIX EPOCH TIME (ミリ秒) 。
""",
    "openapi_examples": {
        "default": {
            "summary": "指定しない (デフォルト)",
            "value": None,
        },
        "normal": {
            "summary": "2024 / 7 / 1 00:00 (JST) より前のコミュニティノートを取得する",
            "value": 1719759600000,
        },
    },
}

v1_data_notes_offset: FastAPIEndpointParamDocs = {
    "description": """
取得するコミュニティノートのリストの先頭からのオフセット。ページネーションに利用される。


ただし、レスポンスの `meta.next` や `meta.prev` で次のページや前のページのリクエスト用 URL が提供されるため、
そちらを利用したほうが良い場合もある。
""",
    "openapi_examples": {
        "default": {
            "summary": "0 (デフォルト)",
            "value": 0,
        },
        "offset_100": {
            "summary": "100",
            "value": 100,
        },
    },
}

v1_data_notes_limit: FastAPIEndpointParamDocs = {
    "description": """
取得するコミュニティノートのリストの最大数。 0 ～ 1000 まで指定できる。ページネーションに利用される。


ただし、レスポンスの `meta.next` や `meta.prev` で次のページや前のページのリクエスト用 URL が提供されるため、
そちらを利用したほうが良い場合もある。
""",
    "openapi_examples": {
        "default": {
            "summary": "100 (デフォルト)",
            "value": 100,
        },
        "limit_50": {
            "summary": "50",
            "value": 50,
        },
    },
}

v1_date_notes_topic_ids: FastAPIEndpointParamDocs = {
    "description": """
取得するコミュニティノートが紐づいているトピックの ID。

`GET /api/v1/data/topics` で取得できるトピックの ID を指定することで、そのトピックに紐づいたコミュニティノートを取得できる。

複数指定した場合は、 **いずれかのトピックに紐づいたコミュニティノート** を取得する。 (AND 検索ではなく OR 検索になる)
""",
    "openapi_examples": {
        "default": {
            "summary": "指定しない (デフォルト)",
            "value": None,
        },
        "single": {
            "summary": "トピックに紐づいたコミュニティノートを取得する",
            "value": [1],
        },
        "multiple_query": {
            "summary": "複数のトピックに紐づいたコミュニティノートを取得する (クエリパラメータ)",
            "value": [1, 2],
        },
        "multiple_comma": {
            "summary": "複数のトピックに紐づいたコミュニティノートを取得する (カンマ区切り)",
            "value": ["1,2"],
        },
    },
}

v1_data_notes_post_ids: FastAPIEndpointParamDocs = {
    "description": """
コミュニティノートのデータ取得に利用する X の Post の ID。
コミュニティノートと Post は 1 : 1 で紐づいている。

複数回クエリパラメータを指定する / カンマ区切りで複数の ID を指定することで複数のコミュニティノートを一括で取得できる。
""",
    "openapi_examples": {
        "default": {
            "summary": "指定しない (デフォルト)",
            "value": None,
        },
        "single": {
            "summary": "Post に紐づいたコミュニティノートを 1つ取得する",
            "value": [SAMPLE_POST_IDS[0]],
        },
        "multiple_query": {
            "summary": "複数の Post について、それぞれに紐づいたコミュニティノートを取得する (クエリパラメータ)",
            "value": SAMPLE_POST_IDS,
        },
        "multiple_comma": {
            "summary": "複数の Post について、それぞれに紐づいたコミュニティノートを取得する (カンマ区切り)",
            "value": [",".join(SAMPLE_POST_IDS)],
        },
    },
}

v1_data_notes_current_status: FastAPIEndpointParamDocs = {
    "description": """
取得するコミュニティノートのステータス。

| X 上の表示                                         | current_statusに指定する値  |
| :------------------------------------------------: | :-------------------------: |
| さらに評価が必要                                   | NEEDS_MORE_RATINGS          |
| 現在のところ「役に立った」と評価されています       | CURRENTLY_RATED_HELPFUL     |
| 現在のところ「役に立たなかった」と評価されています | CURRENTLY_RATED_NOT_HELPFUL |
""",
    "openapi_examples": {
        "default": {
            "summary": "指定しない (デフォルト)",
            "value": None,
        },
        "needs_more_ratings": {
            "summary": "さらに評価が必要なコミュニティノートを取得する",
            "value": ["NEEDS_MORE_RATINGS"],
        },
        "currently_rated_helpful_or_currently_rated_not_helpful": {
            "summary": "評価済みのコミュニティノートを取得する",
            "value": ["CURRENTLY_RATED_HELPFUL", "CURRENTLY_RATED_NOT_HELPFUL"],
        },
    },
}

v1_data_notes_language: FastAPIEndpointParamDocs = {
    "description": """
取得するコミュニティノートの言語。

ISO 639-1 に準拠した 2 文字の言語コードを指定することで、その言語のコミュニティノートのみを取得できる。
""",
    "openapi_examples": {
        "default": {
            "summary": "指定しない (デフォルト)",
            "value": None,
        },
        LanguageIdentifier.EN: {
            "summary": "英語のコミュニティノートを取得する",
            "value": LanguageIdentifier.EN,
        },
        LanguageIdentifier.JA: {
            "summary": "日本語のコミュニティノートを取得する",
            "value": LanguageIdentifier.JA,
        },
    },
}

v1_data_notes_search_text: FastAPIEndpointParamDocs = {
    "description": """
指定した文字列を含む Note を検索して取得する。検索は Note の**Summaryに対して**行われる。
""",
    "openapi_examples": {
        "default": {
            "summary": "指定しない (デフォルト)",
            "value": None,
        },
        "python": {
            "summary": "「Python」を含む Post を取得する",
            "value": "Python",
        },
    },
}


# GET /api/v1/data/notes のクエリパラメータの OpenAPI ドキュメント
V1DataNotesDocs = FastAPIEndpointDocs(
    "コミュニティノートのデータを取得するエンドポイント",
    {
        "note_ids": v1_data_notes_note_ids,
        "created_at_from": v1_data_notes_created_at_from,
        "created_at_to": v1_data_notes_created_at_to,
        "offset": v1_data_notes_offset,
        "limit": v1_data_notes_limit,
        "topic_ids": v1_date_notes_topic_ids,
        "post_ids": v1_data_notes_post_ids,
        "current_status": v1_data_notes_current_status,
        "language": v1_data_notes_language,
        "search_text": v1_data_notes_search_text,
    },
)

# 第2引数を空の辞書にすると mypy に怒られる
# が、第2引数が空の辞書でも怒られない実装にすると param 辞書の補完が効かなくなるので、エラーを無視する
V1DataTopicsDocs = FastAPIEndpointDocs(
    "自動分類されたコミュニティノートのトピック一覧を取得するエンドポイント",
    {},  # type: ignore[var-annotated]
)


v1_data_user_enrollments_participant_id: FastAPIEndpointParamDocs = {
    "description": "取得するコミュニティノート参加ユーザーの ID。",
    "openapi_examples": {
        "single": {
            "summary": "ID: B8B599F50C14003B9520DC8832612831B2D69BFC3B44C8336A800DF725396FBF のユーザーのデータを取得する",
            "value": "B8B599F50C14003B9520DC8832612831B2D69BFC3B44C8336A800DF725396FBF",
        },
    },
}

V1DataUserEnrollmentsDocs = FastAPIEndpointDocs(
    "コミュニティノート参加ユーザーのデータを取得するエンドポイント",
    {
        "participant_id": v1_data_user_enrollments_participant_id,
    },
)

v1_data_x_user_name = FastAPIEndpointParamDocs(
    description="Xのユーザー名",
    openapi_examples={
        "single": {
            "summary": "@以降のユーザ名",
            "value": "elonmusk",
        },
    },
)

v1_data_x_user_follower_count = FastAPIEndpointParamDocs(
    description="Xのユーザーのフォロワー数。",
    openapi_examples={
        "single": {
            "summary": "フォロワー数",
            "value": 100,
        },
    },
)

v1_data_x_user_follow_count = FastAPIEndpointParamDocs(
    description="Xのユーザーのフォロー数。",
    openapi_examples={
        "single": {
            "summary": "フォロー数",
            "value": 100,
        },
    },
)

v1_data_post_favorite_count = FastAPIEndpointParamDocs(
    description="Postのお気に入り数。",
    openapi_examples={
        "single": {
            "summary": "お気に入り数",
            "value": 100,
        },
    },
)

v1_data_post_repost_count = FastAPIEndpointParamDocs(
    description="Postのリポスト数。",
    openapi_examples={
        "single": {
            "summary": "リポスト数",
            "value": 100,
        },
    },
)

v1_data_post_impression_count = FastAPIEndpointParamDocs(
    description="Postのインプレッション数。",
    openapi_examples={
        "single": {
            "summary": "インプレッション数",
            "value": 100,
        },
    },
)

v1_data_post_includes_media = FastAPIEndpointParamDocs(
    description="メディア情報を含んでいるか。",
    openapi_examples={
        "single": {
            "summary": "メディア情報を含める",
            "value": True,
        },
    },
)

# Get /api/v1/data/search の OpenAPI ドキュメント
V1DataSearchDocs = FastAPIEndpointDocs(
    "アドバンスドサーチでデータを取得するエンドポイント",
    {
        "note_includes_text": v1_data_notes_search_text,
        "note_excludes_text": v1_data_notes_search_text,
        "post_includes_text": v1_data_posts_search_text,
        "post_excludes_text": v1_data_posts_search_text,
        "language": v1_data_notes_language,
        "topic_ids": v1_date_notes_topic_ids,
        "note_status": v1_data_notes_current_status,
        "note_created_at_from": v1_data_notes_created_at_from,
        "note_created_at_to": v1_data_notes_created_at_to,
        "x_user_name": v1_data_x_user_name,
        "x_user_followers_count_from": v1_data_x_user_follower_count,
        "x_user_follow_count_from": v1_data_x_user_follow_count,
        "post_favorite_count_from": v1_data_post_favorite_count,
        "post_repost_count_from": v1_data_post_repost_count,
        "post_impression_count_from": v1_data_post_impression_count,
        "post_includes_media": v1_data_post_includes_media,
        "offset": v1_data_posts_offset,
        "limit": v1_data_posts_limit,
    },
)
