from dataclasses import dataclass
from typing import Dict

from fastapi.openapi.models import Example
from typing_extensions import TypedDict


class FastAPIQueryDocsRequired(TypedDict):
    description: str


class FastAPIQueryDocs(FastAPIQueryDocsRequired, total=False):
    openapi_examples: Dict[str, Example]


v1_data_posts_post_id: FastAPIQueryDocs = {
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
        "single": {
            "summary": "Post を 1つ取得する",
            "value": ["1828261879854309500"],
        },
        "multiple_query": {
            "summary": "Post を複数取得する (クエリパラメータ)",
            "value": ["1828261879854309500", "1828261879854309501"],
        },
        "multiple_comma": {
            "summary": "Post を複数取得する (カンマ区切り)",
            "value": ["1828261879854309500,1828261879854309501"],
        },
    },
}

v1_data_posts_note_id: FastAPIQueryDocs = {
    "description": """
Post のデータ取得に利用する X のコミュニティノートの ID。
コミュニティノートと Post は 1 : 1 で紐づいている。

複数回クエリパラメータを指定する / カンマ区切りで複数の ID を指定することで複数の Post を一括で取得できる。
""",
    "openapi_examples": {
        "single": {
            "summary": "コミュニティノートに紐づいた Post を 1つ取得する",
            "value": ["1"],
        },
        "multiple_query": {
            "summary": "複数のコミュニティノートについて、それぞれに紐づいた Post を取得する (クエリパラメータ)",
            "value": ["1", "2"],
        },
        "multiple_comma": {
            "summary": "複数のコミュニティノートについて、それぞれに紐づいた Post を取得する (カンマ区切り)",
            "value": ["1,2"],
        },
    },
}

v1_data_posts_created_at_from: FastAPIQueryDocs = {
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

v1_data_posts_created_at_to: FastAPIQueryDocs = {
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

v1_data_posts_search_text: FastAPIQueryDocs = {
    "description": """
指定した文字列を含む Post を検索して取得する。検索は Post の本文に対して**完全一致**で行われる。
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

v1_data_posts_search_url: FastAPIQueryDocs = {
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

v1_data_posts_media: FastAPIQueryDocs = {
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


@dataclass(frozen=True)
class V1DataPostsQueryDocs:
    """
    `GET /api/v1/data/posts` のクエリパラメータの OpenAPI ドキュメント
    """

    post_id = v1_data_posts_post_id
    note_id = v1_data_posts_note_id
    created_at_from = v1_data_posts_created_at_from
    created_at_to = v1_data_posts_created_at_to
    search_text = v1_data_posts_search_text
    search_url = v1_data_posts_search_url
    media = v1_data_posts_media
