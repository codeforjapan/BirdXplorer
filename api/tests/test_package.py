import re

import birdxplorer_api


def test_package_has_version() -> None:
    assert hasattr(birdxplorer_api, "__version__")
    assert isinstance(birdxplorer_api.__version__, str)
    assert re.match(r"^\d+\.\d+\.\d+$", birdxplorer_api.__version__)
