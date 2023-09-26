from pytest import LogCaptureFixture

from birdxplorer.logger import get_logger


def test_logger_is_a_child_of_root_logger(caplog: LogCaptureFixture) -> None:
    logger = get_logger()
    with caplog.at_level("INFO"):
        logger.info("test")
        assert len(caplog.records) == 1
        assert caplog.records[0].name == "birdxplorer.logger"
        assert caplog.records[0].message == "test"
