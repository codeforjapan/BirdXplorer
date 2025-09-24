import re

import birdxplorer_etl


def test_birdxplorer_etl_has_version() -> None:
    assert hasattr(birdxplorer_etl, "__version__")
    assert isinstance(birdxplorer_etl.__version__, str)
    assert re.match(r"^\d+\.\d+\.\d+$", birdxplorer_etl.__version__)


def test_basic_print() -> None:
    """Basic test that prints 'test' as requested."""
    print("test")
    assert True
