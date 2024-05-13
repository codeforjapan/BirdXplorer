from logging import INFO, Logger, StreamHandler, getLogger

from json_log_formatter import JSONFormatter

LoggerLevelT = int


def get_logger(level: LoggerLevelT = INFO) -> Logger:
    logger = getLogger(__name__)
    if len(logger.handlers) == 0:
        formatter = JSONFormatter()
        stream_handler = StreamHandler()
        stream_handler.setLevel(level=level)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)
    return logger
