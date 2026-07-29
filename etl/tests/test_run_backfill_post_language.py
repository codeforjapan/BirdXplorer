from unittest.mock import MagicMock, patch


@patch("birdxplorer_etl.run_backfill_post_language.SQSHandler")
@patch("birdxplorer_etl.run_backfill_post_language.init_postgresql")
def test_enqueues_only_null_language_posts(mock_init, mock_sqs_cls, monkeypatch):
    monkeypatch.setattr("birdxplorer_etl.run_backfill_post_language.settings.LANG_DETECT_QUEUE_URL", "http://q")
    session = MagicMock()
    session.execute.return_value = [("A", "text a"), ("C", "text c")]  # already-NULL rows only
    mock_init.return_value = session
    sqs = mock_sqs_cls.return_value
    sqs.send_message_batch.return_value = (2, 0)

    from birdxplorer_etl.run_backfill_post_language import main

    rc = main(["--sleep", "0"])
    assert rc == 0
    batch = sqs.send_message_batch.call_args.args[1]
    assert [m["post_id"] for m in batch] == ["A", "C"]
    assert all(m["entity_type"] == "post" and m["processing_type"] == "language_detect" for m in batch)


@patch("birdxplorer_etl.run_backfill_post_language.init_postgresql")
def test_returns_error_when_queue_unset(mock_init, monkeypatch):
    monkeypatch.setattr("birdxplorer_etl.run_backfill_post_language.settings.LANG_DETECT_QUEUE_URL", None)
    from birdxplorer_etl.run_backfill_post_language import main

    assert main([]) == 1
