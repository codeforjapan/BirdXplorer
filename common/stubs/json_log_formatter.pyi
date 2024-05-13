from datetime import datetime
from logging import Formatter, LogRecord
from typing import Union

class JSONFormatter(Formatter):
    def json_record(
        self, message: str, extra: dict[str, Union[None, bool, int, str, float, datetime]], record: LogRecord
    ) -> dict[str, Union[None, bool, int, str, float, datetime]]: ...
