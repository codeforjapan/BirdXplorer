"""
Tests for configuration loader.
"""

import json
import tempfile
from pathlib import Path

import pytest
import yaml  # noqa: F401

from birdxplorer_etl.pipeline.config.config_loader import (
    ConfigLoader,
    ConfigurationError,
    create_sample_config,
    load_config,
)
from birdxplorer_etl.pipeline.config.models import AIConfig  # noqa: F401
from birdxplorer_etl.pipeline.config.models import ExtractionConfig  # noqa: F401
from birdxplorer_etl.pipeline.config.models import (
    ComponentConfig,
    ETLConfig,
    FilterConfig,
)


class TestConfigLoader:
    """Test cases for ConfigLoader class."""

    def create_temp_config_file(self, content: str, suffix: str = ".yaml") -> Path:
        """Helper method to create temporary configuration files."""
        temp_file = tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False)
        temp_file.write(content)
        temp_file.close()
        return Path(temp_file.name)

    def test_load_from_yaml_file(self):
        """Test loading configuration from YAML file."""
        yaml_content = """
pipeline_name: "test_pipeline"
description: "Test YAML pipeline"
version: "1.5"
enabled: true
components:
  - name: "extractor"
    type: "DataExtractor"
    config:
      batch_size: 1000
    enabled: true
    description: "Data extractor component"
filters:
  - name: "quality_filter"
    type: "QualityFilter"
    config:
      min_score: 0.8
    enabled: true
ai_settings:
  model_name: "gpt-4"
  temperature: 0.5
  max_tokens: 2000
  timeout: 60
  retry_attempts: 5
extraction_settings:
  source_type: "database"
  batch_size: 500
  max_retries: 2
  timeout: 120
  parallel_jobs: 3
global_config:
  debug: true
  log_level: "INFO"
"""
        temp_file = self.create_temp_config_file(yaml_content, ".yaml")

        try:
            config = ConfigLoader.load_from_file(temp_file)

            assert config.pipeline_name == "test_pipeline"
            assert config.description == "Test YAML pipeline"
            assert config.version == "1.5"
            assert config.enabled is True

            assert len(config.components) == 1
            comp = config.components[0]
            assert comp.name == "extractor"
            assert comp.type == "DataExtractor"
            assert comp.config["batch_size"] == 1000
            assert comp.enabled is True
            assert comp.description == "Data extractor component"

            assert len(config.filters) == 1
            filt = config.filters[0]
            assert filt.name == "quality_filter"
            assert filt.type == "QualityFilter"
            assert filt.config["min_score"] == 0.8

            assert config.ai_settings.model_name == "gpt-4"
            assert config.ai_settings.temperature == 0.5
            assert config.ai_settings.max_tokens == 2000
            assert config.ai_settings.timeout == 60
            assert config.ai_settings.retry_attempts == 5

            assert config.extraction_settings.source_type == "database"
            assert config.extraction_settings.batch_size == 500
            assert config.extraction_settings.max_retries == 2
            assert config.extraction_settings.timeout == 120
            assert config.extraction_settings.parallel_jobs == 3

            assert config.global_config["debug"] is True
            assert config.global_config["log_level"] == "INFO"

        finally:
            temp_file.unlink()

    def test_load_from_json_file(self):
        """Test loading configuration from JSON file."""
        json_content = {
            "pipeline_name": "json_pipeline",
            "description": "Test JSON pipeline",
            "components": [
                {
                    "name": "transformer",
                    "type": "DataTransformer",
                    "config": {"normalize": True},
                    "enabled": False,
                }
            ],
            "filters": [],
            "ai_settings": {"model_name": "claude-3", "temperature": 0.3},
            "extraction_settings": {"source_type": "api", "batch_size": 2000},
            "global_config": {"environment": "test"},
        }

        temp_file = self.create_temp_config_file(json.dumps(json_content, indent=2), ".json")

        try:
            config = ConfigLoader.load_from_file(temp_file)

            assert config.pipeline_name == "json_pipeline"
            assert config.description == "Test JSON pipeline"

            assert len(config.components) == 1
            comp = config.components[0]
            assert comp.name == "transformer"
            assert comp.type == "DataTransformer"
            assert comp.config["normalize"] is True
            assert comp.enabled is False

            assert len(config.filters) == 0

            assert config.ai_settings.model_name == "claude-3"
            assert config.ai_settings.temperature == 0.3

            assert config.extraction_settings.source_type == "api"
            assert config.extraction_settings.batch_size == 2000

            assert config.global_config["environment"] == "test"

        finally:
            temp_file.unlink()

    def test_load_from_file_nonexistent(self):
        """Test loading from non-existent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            ConfigLoader.load_from_file("nonexistent_file.yaml")

    def test_load_from_file_invalid_yaml(self):
        """Test loading invalid YAML raises ConfigurationError."""
        invalid_yaml = """
pipeline_name: "test"
components:
  - name: "comp1"
    type: "Type1"
  - name: "comp1"  # Invalid: missing closing quotes and indentation
    type: "Type2
"""
        temp_file = self.create_temp_config_file(invalid_yaml)

        try:
            with pytest.raises(ConfigurationError, match="Failed to parse configuration file"):
                ConfigLoader.load_from_file(temp_file)
        finally:
            temp_file.unlink()

    def test_load_from_file_invalid_json(self):
        """Test loading invalid JSON raises ConfigurationError."""
        invalid_json = '{"pipeline_name": "test", "components": [{'
        temp_file = self.create_temp_config_file(invalid_json, ".json")

        try:
            with pytest.raises(ConfigurationError, match="Failed to parse configuration file"):
                ConfigLoader.load_from_file(temp_file)
        finally:
            temp_file.unlink()

    def test_load_from_dict_minimal(self):
        """Test loading from dictionary with minimal configuration."""
        data = {"pipeline_name": "minimal_pipeline"}

        config = ConfigLoader.load_from_dict(data)

        assert config.pipeline_name == "minimal_pipeline"
        assert len(config.components) == 0
        assert len(config.filters) == 0
        assert config.ai_settings is not None  # Default created
        assert config.extraction_settings is not None  # Default created
        assert config.version == "1.0"
        assert config.enabled is True

    def test_load_from_dict_missing_pipeline_name(self):
        """Test loading from dictionary without pipeline_name raises error."""
        data = {"components": []}

        with pytest.raises(ConfigurationError, match="Missing required field: pipeline_name"):
            ConfigLoader.load_from_dict(data)

    def test_load_from_dict_invalid_component(self):
        """Test loading from dictionary with invalid component raises error."""
        data = {"pipeline_name": "test", "components": ["invalid_component"]}

        with pytest.raises(ConfigurationError, match="Invalid component configuration"):
            ConfigLoader.load_from_dict(data)

    def test_load_from_dict_invalid_filter(self):
        """Test loading from dictionary with invalid filter raises error."""
        data = {"pipeline_name": "test", "filters": ["invalid_filter"]}

        with pytest.raises(ConfigurationError, match="Invalid filter configuration"):
            ConfigLoader.load_from_dict(data)

    def test_load_from_dict_invalid_ai_settings(self):
        """Test loading from dictionary with invalid AI settings raises error."""
        data = {"pipeline_name": "test", "ai_settings": "invalid"}

        with pytest.raises(ConfigurationError, match="Invalid ai_settings configuration"):
            ConfigLoader.load_from_dict(data)

    def test_load_from_dict_invalid_extraction_settings(self):
        """Test loading from dictionary with invalid extraction settings raises error."""
        data = {"pipeline_name": "test", "extraction_settings": "invalid"}

        with pytest.raises(ConfigurationError, match="Invalid extraction_settings configuration"):
            ConfigLoader.load_from_dict(data)

    def test_save_to_yaml_file(self):
        """Test saving configuration to YAML file."""
        config = ETLConfig(
            pipeline_name="save_test",
            description="Test saving",
            components=[ComponentConfig(name="comp1", type="Type1")],
            filters=[FilterConfig(name="filter1", type="FilterType1")],
        )

        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as temp_file:
            temp_path = Path(temp_file.name)

        try:
            ConfigLoader.save_to_file(config, temp_path, "yaml")

            # Verify file was created and contains expected content
            assert temp_path.exists()

            with open(temp_path, "r") as f:
                content = f.read()
                assert "pipeline_name: save_test" in content
                assert "description: Test saving" in content
                assert "comp1" in content
                assert "filter1" in content

            # Load back and verify
            loaded_config = ConfigLoader.load_from_file(temp_path)
            assert loaded_config.pipeline_name == "save_test"
            assert loaded_config.description == "Test saving"
            assert len(loaded_config.components) == 1
            assert loaded_config.components[0].name == "comp1"

        finally:
            temp_path.unlink()

    def test_save_to_json_file(self):
        """Test saving configuration to JSON file."""
        config = ETLConfig(
            pipeline_name="save_json_test",
            components=[ComponentConfig(name="comp1", type="Type1", config={"param": "value"})],
        )

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as temp_file:
            temp_path = Path(temp_file.name)

        try:
            ConfigLoader.save_to_file(config, temp_path, "json")

            # Verify file was created and contains valid JSON
            assert temp_path.exists()

            with open(temp_path, "r") as f:
                data = json.load(f)
                assert data["pipeline_name"] == "save_json_test"
                assert len(data["components"]) == 1
                assert data["components"][0]["name"] == "comp1"

            # Load back and verify
            loaded_config = ConfigLoader.load_from_file(temp_path)
            assert loaded_config.pipeline_name == "save_json_test"
            assert len(loaded_config.components) == 1

        finally:
            temp_path.unlink()

    def test_save_unsupported_format(self):
        """Test saving with unsupported format raises ValueError."""
        config = ETLConfig(pipeline_name="test")

        with tempfile.NamedTemporaryFile() as temp_file:
            with pytest.raises(ValueError, match="Unsupported format: xml"):
                ConfigLoader.save_to_file(config, temp_file.name, "xml")

    def test_create_default_config(self):
        """Test creating default configuration."""
        config = ConfigLoader.create_default_config("default_pipeline")

        assert config.pipeline_name == "default_pipeline"
        assert config.description == "Default ETL pipeline configuration"
        assert len(config.components) == 3  # extractor, transformer, loader
        assert len(config.filters) == 1  # default filter
        assert config.ai_settings is not None
        assert config.extraction_settings is not None

        # Check default components
        component_names = [comp.name for comp in config.components]
        assert "default_extractor" in component_names
        assert "default_transformer" in component_names
        assert "default_loader" in component_names

        # Check default filter
        assert config.filters[0].name == "default_filter"

    def test_auto_detect_format(self):
        """Test auto-detection of file format for unknown extensions."""
        # Test YAML content with unknown extension
        yaml_content = """
pipeline_name: "auto_detect_yaml"
components: []
"""
        temp_file = self.create_temp_config_file(yaml_content, ".config")

        try:
            config = ConfigLoader.load_from_file(temp_file)
            assert config.pipeline_name == "auto_detect_yaml"
        finally:
            temp_file.unlink()

        # Test JSON content with unknown extension
        json_content = '{"pipeline_name": "auto_detect_json", "components": []}'
        temp_file = self.create_temp_config_file(json_content, ".config")

        try:
            config = ConfigLoader.load_from_file(temp_file)
            assert config.pipeline_name == "auto_detect_json"
        finally:
            temp_file.unlink()


def test_load_config_convenience_function():
    """Test the convenience load_config function."""
    yaml_content = """
pipeline_name: "convenience_test"
components: []
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as temp_file:
        temp_file.write(yaml_content)
        temp_path = Path(temp_file.name)

    try:
        config = load_config(temp_path)
        assert config.pipeline_name == "convenience_test"
    finally:
        temp_path.unlink()


def test_create_sample_config():
    """Test creating sample configuration file."""
    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as temp_file:
        temp_path = Path(temp_file.name)

    try:
        create_sample_config(temp_path, "yaml")

        # Verify file was created
        assert temp_path.exists()

        # Load and verify sample config
        config = load_config(temp_path)
        assert config.pipeline_name == "language_first_pattern"
        assert config.description == "Sample ETL pipeline configuration"
        assert len(config.components) == 3
        assert len(config.filters) == 1

        # Check specific components
        component_names = [comp.name for comp in config.components]
        assert "note_extractor" in component_names
        assert "note_language_filter" in component_names
        assert "note_transformer" in component_names

        # Check filter
        assert config.filters[0].name == "quality_filter"

        # Check AI settings
        assert config.ai_settings.model_name == "gpt-3.5-turbo"
        assert config.ai_settings.max_tokens == 2000

        # Check extraction settings
        assert config.extraction_settings.batch_size == 500
        assert config.extraction_settings.parallel_jobs == 2

    finally:
        temp_path.unlink()


def test_create_sample_config_json():
    """Test creating sample configuration file in JSON format."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as temp_file:
        temp_path = Path(temp_file.name)

    try:
        create_sample_config(temp_path, "json")

        # Verify file was created and is valid JSON
        assert temp_path.exists()

        with open(temp_path, "r") as f:
            data = json.load(f)
            assert data["pipeline_name"] == "language_first_pattern"

        # Load using config loader
        config = load_config(temp_path)
        assert config.pipeline_name == "language_first_pattern"

    finally:
        temp_path.unlink()
