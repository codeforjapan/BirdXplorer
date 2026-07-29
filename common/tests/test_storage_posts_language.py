from typing import List

from sqlalchemy import update
from sqlalchemy.engine import Engine

from birdxplorer_common.models import Post
from birdxplorer_common.storage import PostRecord, Storage


def test_post_record_has_language_column() -> None:
    assert "language" in PostRecord.__table__.columns


def test_post_model_maps_language(
    engine_for_test: Engine,
    post_samples: List[Post],
    post_records_sample: List[PostRecord],
) -> None:
    storage = Storage(engine=engine_for_test)
    with storage.engine.connect() as conn:
        conn.execute(update(PostRecord).values(language="ja"))
        conn.commit()
    posts = list(storage.get_posts())
    assert all(isinstance(p, Post) for p in posts)
    assert all(p.language == "ja" for p in posts)


def test_get_posts_language_filter(
    engine_for_test: Engine,
    post_samples: List[Post],
    post_records_sample: List[PostRecord],
) -> None:
    storage = Storage(engine=engine_for_test)
    ids = [p.post_id for p in post_samples]
    with storage.engine.connect() as conn:
        conn.execute(update(PostRecord).where(PostRecord.post_id == ids[0]).values(language="ja"))
        conn.execute(update(PostRecord).where(PostRecord.post_id != ids[0]).values(language="en"))
        conn.commit()
    ja = list(storage.get_posts(language_filter=["ja"]))
    assert {p.post_id for p in ja} == {ids[0]}
    assert storage.get_number_of_posts(language_filter=["ja"]) == 1
    assert storage.get_number_of_posts(language_filter=["ja", "en"]) == len(ids)
