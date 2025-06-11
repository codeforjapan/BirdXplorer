"""
Unit tests for ETL pipeline components.

Tests for the new ETL components: NoteExtractorComponent, PostExtractorComponent,
DataTransformerComponent, and DataLoaderComponent.
"""

import pytest
from unittest.mock import Mock, patch

from birdxplorer_etl.pipeline.base import PipelineContext
from birdxplorer_etl.pipeline.components import (
    DataLoaderComponent,
    DataTransformerComponent,
    NoteExtractorComponent,
    PostExtractorComponent,
)


class TestNoteExtractorComponent:
    """Test cases for NoteExtractorComponent."""

    def test_init(self) -> None:
        """Test component initialization."""
        config = {"community_note_days_ago": 5, "use_dummy_data": True}
        component = NoteExtractorComponent("note_extractor", config)

        assert component.name == "note_extractor"
        assert component.config == config

    def test_validate_config_valid(self) -> None:
        """Test configuration validation with valid config."""
        config = {"community_note_days_ago": 3}
        component = NoteExtractorComponent("note_extractor", config)

        # Should not raise any exception
        component.validate_config()

    def test_validate_config_invalid(self) -> None:
        """Test configuration validation with invalid config."""
        config = {"community_note_days_ago": -1}
        component = NoteExtractorComponent("note_extractor", config)

        with pytest.raises(ValueError):
            component.validate_config()

    def test_get_config_values(self) -> None:
        """Test getting configuration values."""
        config = {"community_note_days_ago": 7, "use_dummy_data": False}
        component = NoteExtractorComponent("note_extractor", config)

        assert component.get_config_value("community_note_days_ago") == 7
        assert component.get_config_value("use_dummy_data") is False
        assert component.get_config_value("nonexistent", "default") == "default"


class TestPostExtractorComponent:
    """Test cases for PostExtractorComponent."""

    def test_init(self) -> None:
        """Test component initialization."""
        config = {"target_start_unix_millisecond": 1000, "target_end_unix_millisecond": 2000}
        component = PostExtractorComponent("post_extractor", config)

        assert component.name == "post_extractor"
        assert component.config == config

    def test_validate_config_valid(self) -> None:
        """Test configuration validation with valid config."""
        config = {"target_start_unix_millisecond": 1000, "target_end_unix_millisecond": 2000}
        component = PostExtractorComponent("post_extractor", config)

        # Should not raise any exception
        component.validate_config()

    def test_validate_config_invalid_times(self) -> None:
        """Test configuration validation with invalid time range."""
        config = {"target_start_unix_millisecond": 2000, "target_end_unix_millisecond": 1000}
        component = PostExtractorComponent("post_extractor", config)

        with pytest.raises(ValueError):
            component.validate_config()

    def test_validate_config_invalid_types(self) -> None:
        """Test configuration validation with invalid types."""
        config = {"target_start_unix_millisecond": "invalid", "target_end_unix_millisecond": 2000}
        component = PostExtractorComponent("post_extractor", config)

        with pytest.raises(ValueError):
            component.validate_config()


class TestDataTransformerComponent:
    """Test cases for DataTransformerComponent."""

    def test_init(self) -> None:
        """Test component initialization."""
        config = {"output_directory": "./test_output", "batch_size": 500}
        component = DataTransformerComponent("data_transformer", config)

        assert component.name == "data_transformer"
        assert component.config == config

    def test_validate_config_valid(self) -> None:
        """Test configuration validation with valid config."""
        config = {"output_directory": "./test", "batch_size": 1000}
        component = DataTransformerComponent("data_transformer", config)

        # Should not raise any exception
        component.validate_config()

    def test_validate_config_invalid_directory(self) -> None:
        """Test configuration validation with invalid directory."""
        config = {"output_directory": 123}
        component = DataTransformerComponent("data_transformer", config)

        with pytest.raises(ValueError):
            component.validate_config()

    def test_validate_config_invalid_batch_size(self) -> None:
        """Test configuration validation with invalid batch size."""
        config = {"batch_size": -1}
        component = DataTransformerComponent("data_transformer", config)

        with pytest.raises(ValueError):
            component.validate_config()


class TestDataLoaderComponent:
    """Test cases for DataLoaderComponent."""

    def test_init(self) -> None:
        """Test component initialization."""
        config = {"s3_bucket_name": "test-bucket", "aws_region": "us-east-1"}
        component = DataLoaderComponent("data_loader", config)

        assert component.name == "data_loader"
        assert component.config == config

    def test_validate_config_valid(self) -> None:
        """Test configuration validation with valid config."""
        config = {
            "s3_bucket_name": "test-bucket",
            "aws_region": "us-east-1",
            "input_directory": "./data"
        }
        component = DataLoaderComponent("data_loader", config)

        # Should not raise any exception
        component.validate_config()

    def test_validate_config_missing_bucket(self) -> None:
        """Test configuration validation with missing bucket name."""
        config = {"aws_region": "us-east-1"}
        component = DataLoaderComponent("data_loader", config)

        with pytest.raises(ValueError):
            component.validate_config()

    def test_validate_config_invalid_region(self) -> None:
        """Test configuration validation with invalid region type."""
        config = {"s3_bucket_name": "test-bucket", "aws_region": 123}
        component = DataLoaderComponent("data_loader", config)

        with pytest.raises(ValueError):
            component.validate_config()

    def test_validate_config_invalid_input_directory(self) -> None:
        """Test configuration validation with invalid input directory."""
        config = {"s3_bucket_name": "test-bucket", "input_directory": 123}
        component = DataLoaderComponent("data_loader", config)

        with pytest.raises(ValueError):
            component.validate_config()

    @patch('boto3.client')
    def test_setup(self, mock_boto3_client) -> None:
        """Test component setup."""
        mock_s3_client = Mock()
        mock_boto3_client.return_value = mock_s3_client

        config = {"s3_bucket_name": "test-bucket", "aws_region": "us-east-1"}
        component = DataLoaderComponent("data_loader", config)
        context = PipelineContext()

        component.setup(context)

        mock_boto3_client.assert_called_once_with("s3", region_name="us-east-1")
        assert component.s3_client is mock_s3_client


class TestComponentsImport:
    """Test that all components can be imported correctly."""

    def test_import_all_components(self) -> None:
        """Test that all components can be imported."""
        from birdxplorer_etl.pipeline.components import (
            DataLoaderComponent,
            DataTransformerComponent,
            NoteExtractorComponent,
            PostExtractorComponent,
        )

        # Verify all components are available
        assert NoteExtractorComponent is not None
        assert PostExtractorComponent is not None
        assert DataTransformerComponent is not None
        assert DataLoaderComponent is not None

    def test_components_inherit_from_base(self) -> None:
        """Test that all components inherit from PipelineComponent."""
        from birdxplorer_etl.pipeline.base import PipelineComponent
        from birdxplorer_etl.pipeline.components import (
            DataLoaderComponent,
            DataTransformerComponent,
            NoteExtractorComponent,
            PostExtractorComponent,
        )

        assert issubclass(NoteExtractorComponent, PipelineComponent)
        assert issubclass(PostExtractorComponent, PipelineComponent)
        assert issubclass(DataTransformerComponent, PipelineComponent)
        assert issubclass(DataLoaderComponent, PipelineComponent)


class TestCompatibilityLayer:
    """Test the compatibility layer functions."""

    def test_extract_import(self) -> None:
        """Test that extract_data can be imported."""
        from birdxplorer_etl.extract import extract_data
        assert extract_data is not None

    def test_transform_import(self) -> None:
        """Test that transform_data can be imported."""
        from birdxplorer_etl.transform import transform_data
        assert transform_data is not None

    def test_load_import(self) -> None:
        """Test that load_data can be imported."""
        from birdxplorer_etl.load import load_data
        assert load_data is not None

    def test_legacy_functions_import(self) -> None:
        """Test that legacy functions can be imported."""
        from birdxplorer_etl.transform import (
            generate_note_topic,
            generate_post_link,
            write_media_csv,
        )
        
        assert generate_note_topic is not None
        assert generate_post_link is not None
        assert write_media_csv is not None