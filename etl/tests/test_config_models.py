"""
Tests for configuration data models.
"""

import pytest

from birdxplorer_etl.pipeline.config.models import (
    AIConfig,
    ComponentConfig,
    ETLConfig,
    ExtractionConfig,
    FilterConfig,
)


class TestComponentConfig:
    """Test cases for ComponentConfig class."""

    def test_valid_component_config(self):
        """Test creating a valid component configuration."""
        config = ComponentConfig(
            name="test_component",
            type="TestComponent",
            config={"param1": "value1"},
            enabled=True,
            description="Test component",
        )
        assert config.name == "test_component"
        assert config.type == "TestComponent"
        assert config.config == {"param1": "value1"}
        assert config.enabled is True
        assert config.description == "Test component"

    def test_component_config_defaults(self):
        """Test component configuration with default values."""
        config = ComponentConfig(name="test", type="Test")
        assert config.config == {}
        assert config.enabled is True
        assert config.description is None

    def test_empty_component_name_raises_error(self):
        """Test that empty component name raises ValueError."""
        with pytest.raises(ValueError, match="Component name cannot be empty"):
            ComponentConfig(name="", type="Test")

    def test_empty_component_type_raises_error(self):
        """Test that empty component type raises ValueError."""
        with pytest.raises(ValueError, match="Component type cannot be empty"):
            ComponentConfig(name="test", type="")


class TestFilterConfig:
    """Test cases for FilterConfig class."""

    def test_valid_filter_config(self):
        """Test creating a valid filter configuration."""
        config = FilterConfig(
            name="test_filter",
            type="TestFilter",
            config={"threshold": 0.5},
            enabled=False,
            description="Test filter",
        )
        assert config.name == "test_filter"
        assert config.type == "TestFilter"
        assert config.config == {"threshold": 0.5}
        assert config.enabled is False
        assert config.description == "Test filter"

    def test_filter_config_defaults(self):
        """Test filter configuration with default values."""
        config = FilterConfig(name="test", type="Test")
        assert config.config == {}
        assert config.enabled is True
        assert config.description is None

    def test_empty_filter_name_raises_error(self):
        """Test that empty filter name raises ValueError."""
        with pytest.raises(ValueError, match="Filter name cannot be empty"):
            FilterConfig(name="", type="Test")

    def test_empty_filter_type_raises_error(self):
        """Test that empty filter type raises ValueError."""
        with pytest.raises(ValueError, match="Filter type cannot be empty"):
            FilterConfig(name="test", type="")


class TestAIConfig:
    """Test cases for AIConfig class."""

    def test_valid_ai_config(self):
        """Test creating a valid AI configuration."""
        config = AIConfig(
            model_name="gpt-4",
            temperature=0.5,
            max_tokens=1000,
            api_key="test-key",
            base_url="https://api.example.com",
            timeout=60,
            retry_attempts=5,
            config={"custom": "value"},
        )
        assert config.model_name == "gpt-4"
        assert config.temperature == 0.5
        assert config.max_tokens == 1000
        assert config.api_key == "test-key"
        assert config.base_url == "https://api.example.com"
        assert config.timeout == 60
        assert config.retry_attempts == 5
        assert config.config == {"custom": "value"}

    def test_ai_config_defaults(self):
        """Test AI configuration with default values."""
        config = AIConfig()
        assert config.model_name == "gpt-3.5-turbo"
        assert config.temperature == 0.7
        assert config.max_tokens is None
        assert config.api_key is None
        assert config.base_url is None
        assert config.timeout == 30
        assert config.retry_attempts == 3
        assert config.config == {}

    def test_invalid_temperature_raises_error(self):
        """Test that invalid temperature raises ValueError."""
        with pytest.raises(ValueError, match="Temperature must be between 0 and 2"):
            AIConfig(temperature=-0.1)

        with pytest.raises(ValueError, match="Temperature must be between 0 and 2"):
            AIConfig(temperature=2.1)

    def test_invalid_max_tokens_raises_error(self):
        """Test that invalid max_tokens raises ValueError."""
        with pytest.raises(ValueError, match="Max tokens must be positive"):
            AIConfig(max_tokens=0)

        with pytest.raises(ValueError, match="Max tokens must be positive"):
            AIConfig(max_tokens=-10)

    def test_invalid_timeout_raises_error(self):
        """Test that invalid timeout raises ValueError."""
        with pytest.raises(ValueError, match="Timeout must be positive"):
            AIConfig(timeout=0)

        with pytest.raises(ValueError, match="Timeout must be positive"):
            AIConfig(timeout=-10)

    def test_invalid_retry_attempts_raises_error(self):
        """Test that invalid retry_attempts raises ValueError."""
        with pytest.raises(ValueError, match="Retry attempts cannot be negative"):
            AIConfig(retry_attempts=-1)


class TestExtractionConfig:
    """Test cases for ExtractionConfig class."""

    def test_valid_extraction_config(self):
        """Test creating a valid extraction configuration."""
        config = ExtractionConfig(
            source_type="api",
            connection_string="postgresql://user:pass@localhost:5432/db",
            batch_size=500,
            max_retries=5,
            timeout=600,
            parallel_jobs=4,
            config={"custom": "setting"},
        )
        assert config.source_type == "api"
        assert config.connection_string == "postgresql://user:pass@localhost:5432/db"
        assert config.batch_size == 500
        assert config.max_retries == 5
        assert config.timeout == 600
        assert config.parallel_jobs == 4
        assert config.config == {"custom": "setting"}

    def test_extraction_config_defaults(self):
        """Test extraction configuration with default values."""
        config = ExtractionConfig()
        assert config.source_type == "database"
        assert config.connection_string is None
        assert config.batch_size == 1000
        assert config.max_retries == 3
        assert config.timeout == 300
        assert config.parallel_jobs == 1
        assert config.config == {}

    def test_invalid_batch_size_raises_error(self):
        """Test that invalid batch_size raises ValueError."""
        with pytest.raises(ValueError, match="Batch size must be positive"):
            ExtractionConfig(batch_size=0)

        with pytest.raises(ValueError, match="Batch size must be positive"):
            ExtractionConfig(batch_size=-10)

    def test_invalid_max_retries_raises_error(self):
        """Test that invalid max_retries raises ValueError."""
        with pytest.raises(ValueError, match="Max retries cannot be negative"):
            ExtractionConfig(max_retries=-1)

    def test_invalid_timeout_raises_error(self):
        """Test that invalid timeout raises ValueError."""
        with pytest.raises(ValueError, match="Timeout must be positive"):
            ExtractionConfig(timeout=0)

        with pytest.raises(ValueError, match="Timeout must be positive"):
            ExtractionConfig(timeout=-10)

    def test_invalid_parallel_jobs_raises_error(self):
        """Test that invalid parallel_jobs raises ValueError."""
        with pytest.raises(ValueError, match="Parallel jobs must be positive"):
            ExtractionConfig(parallel_jobs=0)

        with pytest.raises(ValueError, match="Parallel jobs must be positive"):
            ExtractionConfig(parallel_jobs=-1)


class TestETLConfig:
    """Test cases for ETLConfig class."""

    def test_valid_etl_config(self):
        """Test creating a valid ETL configuration."""
        component = ComponentConfig(name="comp1", type="Component1")
        filter_config = FilterConfig(name="filter1", type="Filter1")
        ai_config = AIConfig(model_name="gpt-4")
        extraction_config = ExtractionConfig(source_type="api")

        config = ETLConfig(
            pipeline_name="test_pipeline",
            components=[component],
            filters=[filter_config],
            ai_settings=ai_config,
            extraction_settings=extraction_config,
            global_config={"debug": True},
            description="Test pipeline",
            version="2.0",
            enabled=False,
        )

        assert config.pipeline_name == "test_pipeline"
        assert len(config.components) == 1
        assert config.components[0].name == "comp1"
        assert len(config.filters) == 1
        assert config.filters[0].name == "filter1"
        assert config.ai_settings.model_name == "gpt-4"
        assert config.extraction_settings.source_type == "api"
        assert config.global_config == {"debug": True}
        assert config.description == "Test pipeline"
        assert config.version == "2.0"
        assert config.enabled is False

    def test_etl_config_defaults(self):
        """Test ETL configuration with default values."""
        config = ETLConfig(pipeline_name="test")
        assert config.components == []
        assert config.filters == []
        assert config.ai_settings is not None
        assert config.extraction_settings is not None
        assert config.global_config == {}
        assert config.description is None
        assert config.version == "1.0"
        assert config.enabled is True

    def test_empty_pipeline_name_raises_error(self):
        """Test that empty pipeline name raises ValueError."""
        with pytest.raises(ValueError, match="Pipeline name cannot be empty"):
            ETLConfig(pipeline_name="")

    def test_duplicate_component_names_raises_error(self):
        """Test that duplicate component names raise ValueError."""
        component1 = ComponentConfig(name="duplicate", type="Component1")
        component2 = ComponentConfig(name="duplicate", type="Component2")

        with pytest.raises(ValueError, match="Component names must be unique"):
            ETLConfig(pipeline_name="test", components=[component1, component2])

    def test_duplicate_filter_names_raises_error(self):
        """Test that duplicate filter names raise ValueError."""
        filter1 = FilterConfig(name="duplicate", type="Filter1")
        filter2 = FilterConfig(name="duplicate", type="Filter2")

        with pytest.raises(ValueError, match="Filter names must be unique"):
            ETLConfig(pipeline_name="test", filters=[filter1, filter2])

    def test_get_component_by_name(self):
        """Test getting component by name."""
        component1 = ComponentConfig(name="comp1", type="Component1")
        component2 = ComponentConfig(name="comp2", type="Component2")
        config = ETLConfig(pipeline_name="test", components=[component1, component2])

        found = config.get_component_by_name("comp1")
        assert found is not None
        assert found.name == "comp1"
        assert found.type == "Component1"

        not_found = config.get_component_by_name("nonexistent")
        assert not_found is None

    def test_get_filter_by_name(self):
        """Test getting filter by name."""
        filter1 = FilterConfig(name="filter1", type="Filter1")
        filter2 = FilterConfig(name="filter2", type="Filter2")
        config = ETLConfig(pipeline_name="test", filters=[filter1, filter2])

        found = config.get_filter_by_name("filter1")
        assert found is not None
        assert found.name == "filter1"
        assert found.type == "Filter1"

        not_found = config.get_filter_by_name("nonexistent")
        assert not_found is None

    def test_get_enabled_components(self):
        """Test getting enabled components."""
        comp1 = ComponentConfig(name="comp1", type="Component1", enabled=True)
        comp2 = ComponentConfig(name="comp2", type="Component2", enabled=False)
        comp3 = ComponentConfig(name="comp3", type="Component3", enabled=True)
        config = ETLConfig(pipeline_name="test", components=[comp1, comp2, comp3])

        enabled = config.get_enabled_components()
        assert len(enabled) == 2
        assert enabled[0].name == "comp1"
        assert enabled[1].name == "comp3"

    def test_get_enabled_filters(self):
        """Test getting enabled filters."""
        filter1 = FilterConfig(name="filter1", type="Filter1", enabled=True)
        filter2 = FilterConfig(name="filter2", type="Filter2", enabled=False)
        filter3 = FilterConfig(name="filter3", type="Filter3", enabled=True)
        config = ETLConfig(pipeline_name="test", filters=[filter1, filter2, filter3])

        enabled = config.get_enabled_filters()
        assert len(enabled) == 2
        assert enabled[0].name == "filter1"
        assert enabled[1].name == "filter3"

    def test_to_dict(self):
        """Test converting configuration to dictionary."""
        component = ComponentConfig(name="comp1", type="Component1", config={"param": "value"})
        filter_config = FilterConfig(name="filter1", type="Filter1")
        ai_config = AIConfig(model_name="gpt-4", temperature=0.5)
        extraction_config = ExtractionConfig(source_type="api", batch_size=500)

        config = ETLConfig(
            pipeline_name="test_pipeline",
            components=[component],
            filters=[filter_config],
            ai_settings=ai_config,
            extraction_settings=extraction_config,
            global_config={"debug": True},
            description="Test pipeline",
            version="2.0",
        )

        result = config.to_dict()

        assert result["pipeline_name"] == "test_pipeline"
        assert result["description"] == "Test pipeline"
        assert result["version"] == "2.0"
        assert result["enabled"] is True
        assert len(result["components"]) == 1
        assert result["components"][0]["name"] == "comp1"
        assert result["components"][0]["config"] == {"param": "value"}
        assert len(result["filters"]) == 1
        assert result["filters"][0]["name"] == "filter1"
        assert result["ai_settings"]["model_name"] == "gpt-4"
        assert result["ai_settings"]["temperature"] == 0.5
        assert result["extraction_settings"]["source_type"] == "api"
        assert result["extraction_settings"]["batch_size"] == 500
        assert result["global_config"] == {"debug": True}