"""
Unit tests for PipelineComponent class.
"""

from typing import Any, Dict

import pytest

from birdxplorer_etl.pipeline.base import (
    PipelineComponent,
    PipelineComponentError,
    PipelineContext,
)


class TestComponent(PipelineComponent):
    """Test implementation of PipelineComponent for testing."""

    def __init__(self, name: str, config: Dict[str, Any] = None, should_fail: bool = False) -> None:
        super().__init__(name, config)
        self.should_fail = should_fail
        self.setup_called = False
        self.execute_called = False
        self.teardown_called = False

    def execute(self, context: PipelineContext) -> PipelineContext:
        """Test execute implementation."""
        self.execute_called = True
        if self.should_fail:
            raise PipelineComponentError(self, "Test failure")

        # Add some test data to context
        context.set_data(f"{self.name}_executed", True)
        return context

    def setup(self, context: PipelineContext) -> None:
        """Test setup implementation."""
        self.setup_called = True

    def teardown(self, context: PipelineContext) -> None:
        """Test teardown implementation."""
        self.teardown_called = True


class TestPipelineComponent:
    """Test cases for PipelineComponent class."""

    def test_init_basic(self) -> None:
        """Test basic initialization."""
        component = TestComponent("test_component")

        assert component.name == "test_component"
        assert component.config == {}

    def test_init_with_config(self) -> None:
        """Test initialization with configuration."""
        config = {"param1": "value1", "param2": 42}
        component = TestComponent("test_component", config)

        assert component.name == "test_component"
        assert component.config == config

    def test_execute(self) -> None:
        """Test successful execution."""
        component = TestComponent("test_component")
        context = PipelineContext()

        result = component.execute(context)

        assert component.execute_called
        assert result.get_data("test_component_executed") is True

    def test_execute_with_error(self) -> None:
        """Test execution with error."""
        component = TestComponent("test_component", should_fail=True)
        context = PipelineContext()

        with pytest.raises(PipelineComponentError) as exc_info:
            component.execute(context)

        assert component.execute_called
        assert exc_info.value.component == component
        assert "Test failure" in str(exc_info.value)

    def test_setup_teardown(self) -> None:
        """Test setup and teardown methods."""
        component = TestComponent("test_component")
        context = PipelineContext()

        component.setup(context)
        assert component.setup_called

        component.teardown(context)
        assert component.teardown_called

    def test_get_config_value(self) -> None:
        """Test getting configuration values."""
        config = {"param1": "value1", "param2": 42}
        component = TestComponent("test_component", config)

        assert component.get_config_value("param1") == "value1"
        assert component.get_config_value("param2") == 42
        assert component.get_config_value("nonexistent") is None
        assert component.get_config_value("nonexistent", "default") == "default"

    def test_validate_config(self) -> None:
        """Test configuration validation (default implementation does nothing)."""
        component = TestComponent("test_component")

        # Should not raise any exception
        component.validate_config()

    def test_str_repr(self) -> None:
        """Test string representations."""
        config = {"param": "value"}
        component = TestComponent("test_component", config)

        assert str(component) == "TestComponent(name='test_component')"
        assert repr(component) == "TestComponent(name='test_component', config={'param': 'value'})"


class TestPipelineComponentError:
    """Test cases for PipelineComponentError class."""

    def test_init_basic(self) -> None:
        """Test basic error initialization."""
        component = TestComponent("test_component")
        error = PipelineComponentError(component, "Test error message")

        assert error.component == component
        assert error.cause is None
        assert "Component 'test_component' error: Test error message" in str(error)

    def test_init_with_cause(self) -> None:
        """Test error initialization with underlying cause."""
        component = TestComponent("test_component")
        cause = ValueError("Underlying error")
        error = PipelineComponentError(component, "Test error message", cause)

        assert error.component == component
        assert error.cause == cause
        assert "Component 'test_component' error: Test error message" in str(error)
