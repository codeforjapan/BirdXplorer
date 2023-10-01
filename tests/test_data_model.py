import csv
import os
import re

from birdxplorer.models import UserEnrollment


def test_user_enrollment() -> None:
    data_dir = os.environ.get("DATA_DIR", "")
    if data_dir == "":
        return
    loaded = False
    for fn in os.listdir(data_dir):
        if re.match(r"userEnrollment-[0-9]{5}.tsv", fn) is None:
            continue
        loaded = True
        with open(os.path.join(data_dir, fn), "r", encoding="utf-8") as fin:
            reader = csv.DictReader(fin, delimiter="\t")
            for row in reader:
                _ = UserEnrollment(**row)
    assert loaded
