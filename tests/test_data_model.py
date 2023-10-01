import csv
import os
import re
from abc import ABC, abstractmethod
from collections.abc import Mapping

from birdxplorer.models import UserEnrollment


class BaseDataModelTester(ABC):
    def __init__(self, file_name_regex: re.Pattern[str]) -> None:
        self._file_name_regex = file_name_regex

    @property
    def file_name_regex(self) -> re.Pattern[str]:
        return self._file_name_regex

    @abstractmethod
    def validate(self, row: Mapping[str, str]) -> None:
        raise NotImplementedError

    def __call__(self) -> None:
        data_dir = os.environ.get("DATA_DIR", "")
        if data_dir == "":
            return
        loaded = False
        for fn in os.listdir(data_dir):
            if self.file_name_regex.match(fn) is None:
                continue
            loaded = True
            with open(os.path.join(data_dir, fn), "r", encoding="utf-8") as fin:
                reader = csv.DictReader(fin, delimiter="\t")
                for row in reader:
                    self.validate(row)
        assert loaded


class UserEnrollmentTester(BaseDataModelTester):
    def __init__(self) -> None:
        super(UserEnrollmentTester, self).__init__(re.compile(r"userEnrollment-[0-9]{5}.tsv"))

    def validate(self, row: Mapping[str, str]) -> None:
        _ = UserEnrollment(**row)


def test_user_enrollment() -> None:
    UserEnrollmentTester()()
