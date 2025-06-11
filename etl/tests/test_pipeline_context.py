"""
Unit tests for PipelineContext class.
"""

from logging import Logger

from birdxplorer_etl.pipeline.base import PipelineContext


class TestPipelineContext:
    """Test cases for PipelineContext class."""

    def test_init_empty(self) -> None:
        """Test initialization with default values."""
        context = PipelineContext()

        assert context.data == {}
        assert context.config == {}
        assert context.metadata == {}
        assert isinstance(context.logger, Logger)

    def test_init_with_values(self) -> None:
        """Test initialization with provided values."""
        data = {"key1": "value1"}
        config = {"key2": "value2"}
        metadata = {"key3": "value3"}

        context = PipelineContext(data=data, config=config, metadata=metadata)

        assert context.data == data
        assert context.config == config
        assert context.metadata == metadata
        assert isinstance(context.logger, Logger)

    def test_set_get_data(self) -> None:
        """Test setting and getting data values."""
        context = PipelineContext()

        context.set_data("test_key", "test_value")
        assert context.get_data("test_key") == "test_value"
        assert context.get_data("nonexistent") is None
        assert context.get_data("nonexistent", "default") == "default"

    def test_set_get_config(self) -> None:
        """Test setting and getting config values."""
        context = PipelineContext()

        context.set_config("config_key", "config_value")
        assert context.get_config("config_key") == "config_value"
        assert context.get_config("nonexistent") is None
        assert context.get_config("nonexistent", "default") == "default"

    def test_set_get_metadata(self) -> None:
        """Test setting and getting metadata values."""
        context = PipelineContext()

        context.set_metadata("meta_key", "meta_value")
        assert context.get_metadata("meta_key") == "meta_value"
        assert context.get_metadata("nonexistent") is None
        assert context.get_metadata("nonexistent", "default") == "default"

    def test_copy(self) -> None:
        """Test creating a copy of the context."""
        original = PipelineContext()
        original.set_data("data_key", "data_value")
        original.set_config("config_key", "config_value")
        original.set_metadata("meta_key", "meta_value")

        copy = original.copy()

        # Verify all values are copied
        assert copy.get_data("data_key") == "data_value"
        assert copy.get_config("config_key") == "config_value"
        assert copy.get_metadata("meta_key") == "meta_value"

        # Verify it's a shallow copy (dictionaries are different objects)
        assert copy.data is not original.data
        assert copy.config is not original.config
        assert copy.metadata is not original.metadata

        # Verify logger is shared
        assert copy.logger is original.logger

        # Verify modifying copy doesn't affect original
        copy.set_data("new_key", "new_value")
        assert original.get_data("new_key") is None
