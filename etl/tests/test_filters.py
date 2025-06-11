"""
Unit tests for the filtering system.

This module contains comprehensive tests for the Filter base class,
FilterChain, FilterFactory, and basic filter implementations.
"""

import pytest
from typing import List
from unittest.mock import MagicMock, Mock

from birdxplorer_common.storage import RowNoteRecord
from birdxplorer_etl.pipeline.config.models import FilterConfig
from birdxplorer_etl.pipeline.filters import (
    Filter,
    FilterError,
    FilterChain,
    FilterFactory,
    FilterRegistry,
    DateRangeFilter,
    ClassificationFilter,
    SummaryLengthFilter,
    BelievabilityFilter,
)


class MockFilter(Filter):
    """Mock filter for testing purposes."""

    def __init__(self, name: str, filter_count: int = 0) -> None:
        super().__init__(name)
        self.filter_count = filter_count
        self.call_count = 0

    def apply(self, notes: List[RowNoteRecord]) -> List[RowNoteRecord]:
        self.call_count += 1
        return notes[self.filter_count:]


class FailingFilter(Filter):
    """Mock filter that always raises an exception."""

    def apply(self, notes: List[RowNoteRecord]) -> List[RowNoteRecord]:
        raise ValueError("Test filter failure")


@pytest.fixture
def mock_notes():
    """Create mock RowNoteRecord instances for testing."""
    notes = []
    for i in range(10):
        note = Mock(spec=RowNoteRecord)
        note.note_id = f"note_{i}"
        note.created_at_millis = 1000000000000 + i * 1000
        note.summary = f"Test summary {i}" + "x" * (i * 10)  # Variable length
        note.classification = "NOT_MISLEADING" if i % 2 == 0 else "MISINFORMED_OR_POTENTIALLY_MISLEADING"
        note.believable = "1" if i % 3 == 0 else "0"
        notes.append(note)
    return notes


class TestFilter:
    """Test cases for the Filter base class."""

    def test_filter_initialization(self):
        """Test Filter initialization."""
        filter_instance = MockFilter("test_filter")
        assert filter_instance.get_name() == "test_filter"
        assert str(filter_instance) == "MockFilter(name='test_filter')"
        assert repr(filter_instance) == "MockFilter(name='test_filter')"

    def test_filter_abstract_method(self):
        """Test that Filter is abstract and cannot be instantiated directly."""
        with pytest.raises(TypeError):
            Filter("test")

    def test_mock_filter_apply(self, mock_notes):
        """Test MockFilter apply method."""
        filter_instance = MockFilter("test", filter_count=3)
        result = filter_instance.apply(mock_notes)
        assert len(result) == 7  # 10 - 3
        assert filter_instance.call_count == 1


class TestFilterError:
    """Test cases for the FilterError exception."""

    def test_filter_error_creation(self):
        """Test FilterError creation."""
        filter_instance = MockFilter("test_filter")
        error = FilterError(filter_instance, "Test error")
        
        assert error.filter == filter_instance
        assert "Filter 'test_filter' error: Test error" in str(error)

    def test_filter_error_with_cause(self):
        """Test FilterError creation with underlying cause."""
        filter_instance = MockFilter("test_filter")
        cause = ValueError("Original error")
        error = FilterError(filter_instance, "Test error", cause)
        
        assert error.filter == filter_instance
        assert error.cause == cause


class TestFilterChain:
    """Test cases for the FilterChain class."""

    def test_filter_chain_initialization(self):
        """Test FilterChain initialization."""
        chain = FilterChain("test_chain")
        assert chain.name == "test_chain"
        assert len(chain) == 0
        assert chain.get_filter_names() == []

    def test_filter_chain_add_remove_filters(self):
        """Test adding and removing filters from chain."""
        chain = FilterChain("test_chain")
        filter1 = MockFilter("filter1")
        filter2 = MockFilter("filter2")
        
        # Add filters
        chain.add_filter(filter1)
        chain.add_filter(filter2)
        assert len(chain) == 2
        assert chain.get_filter_names() == ["filter1", "filter2"]
        
        # Remove filter
        assert chain.remove_filter("filter1") is True
        assert len(chain) == 1
        assert chain.get_filter_names() == ["filter2"]
        
        # Try to remove non-existent filter
        assert chain.remove_filter("non_existent") is False

    def test_filter_chain_insert_filter(self):
        """Test inserting filter at specific position."""
        chain = FilterChain("test_chain")
        filter1 = MockFilter("filter1")
        filter2 = MockFilter("filter2")
        filter3 = MockFilter("filter3")
        
        chain.add_filter(filter1)
        chain.add_filter(filter3)
        chain.insert_filter(1, filter2)
        
        assert chain.get_filter_names() == ["filter1", "filter2", "filter3"]

    def test_filter_chain_apply_empty(self, mock_notes):
        """Test applying empty filter chain."""
        chain = FilterChain("test_chain")
        result = chain.apply(mock_notes)
        assert result == mock_notes

    def test_filter_chain_apply_single_filter(self, mock_notes):
        """Test applying filter chain with single filter."""
        chain = FilterChain("test_chain")
        filter1 = MockFilter("filter1", filter_count=3)
        chain.add_filter(filter1)
        
        result = chain.apply(mock_notes)
        assert len(result) == 7
        assert filter1.call_count == 1

    def test_filter_chain_apply_multiple_filters(self, mock_notes):
        """Test applying filter chain with multiple filters."""
        chain = FilterChain("test_chain")
        filter1 = MockFilter("filter1", filter_count=2)
        filter2 = MockFilter("filter2", filter_count=3)
        chain.add_filter(filter1)
        chain.add_filter(filter2)
        
        result = chain.apply(mock_notes)
        assert len(result) == 5  # 10 - 2 - 3
        assert filter1.call_count == 1
        assert filter2.call_count == 1

    def test_filter_chain_apply_with_failure(self, mock_notes):
        """Test filter chain behavior when a filter fails."""
        chain = FilterChain("test_chain")
        filter1 = MockFilter("filter1")
        failing_filter = FailingFilter("failing_filter")
        filter3 = MockFilter("filter3")
        
        chain.add_filter(filter1)
        chain.add_filter(failing_filter)
        chain.add_filter(filter3)
        
        with pytest.raises(FilterError) as exc_info:
            chain.apply(mock_notes)
        
        assert "failing_filter" in str(exc_info.value)
        assert filter1.call_count == 1
        assert filter3.call_count == 0  # Should not be called after failure

    def test_filter_chain_clear(self):
        """Test clearing all filters from chain."""
        chain = FilterChain("test_chain")
        chain.add_filter(MockFilter("filter1"))
        chain.add_filter(MockFilter("filter2"))
        
        assert len(chain) == 2
        chain.clear()
        assert len(chain) == 0


class TestFilterRegistry:
    """Test cases for the FilterRegistry class."""

    def test_registry_initialization(self):
        """Test FilterRegistry initialization."""
        registry = FilterRegistry()
        assert registry.get_registered_types() == []

    def test_registry_register_filter(self):
        """Test registering a filter type."""
        registry = FilterRegistry()
        registry.register("mock", MockFilter)
        
        assert "mock" in registry.get_registered_types()
        assert registry.is_registered("mock")
        assert registry.get_filter_class("mock") == MockFilter

    def test_registry_register_duplicate(self):
        """Test registering duplicate filter type raises error."""
        registry = FilterRegistry()
        registry.register("mock", MockFilter)
        
        with pytest.raises(ValueError, match="already registered"):
            registry.register("mock", MockFilter)

    def test_registry_register_invalid_class(self):
        """Test registering non-filter class raises error."""
        registry = FilterRegistry()
        
        with pytest.raises(ValueError, match="inherit from Filter"):
            registry.register("invalid", str)

    def test_registry_unregister(self):
        """Test unregistering a filter type."""
        registry = FilterRegistry()
        registry.register("mock", MockFilter)
        
        assert registry.unregister("mock") is True
        assert not registry.is_registered("mock")
        assert registry.unregister("non_existent") is False

    def test_registry_get_unknown_filter(self):
        """Test getting unknown filter type raises error."""
        registry = FilterRegistry()
        
        with pytest.raises(ValueError, match="Unknown filter type"):
            registry.get_filter_class("unknown")


class TestFilterFactory:
    """Test cases for the FilterFactory class."""

    def test_factory_initialization(self):
        """Test FilterFactory initialization."""
        factory = FilterFactory()
        assert factory.get_registry() is not None

    def test_factory_create_filter(self):
        """Test creating a filter from configuration."""
        registry = FilterRegistry()
        registry.register("mock", MockFilter)
        factory = FilterFactory(registry)
        
        config = FilterConfig(name="test_filter", type="mock")
        filter_instance = factory.create_filter(config)
        
        assert isinstance(filter_instance, MockFilter)
        assert filter_instance.get_name() == "test_filter"

    def test_factory_create_filter_unknown_type(self):
        """Test creating filter with unknown type raises error."""
        factory = FilterFactory()
        config = FilterConfig(name="test_filter", type="unknown")
        
        with pytest.raises(FilterError):
            factory.create_filter(config)

    def test_factory_create_filter_chain(self):
        """Test creating a filter chain from configurations."""
        registry = FilterRegistry()
        registry.register("mock", MockFilter)
        factory = FilterFactory(registry)
        
        configs = [
            FilterConfig(name="filter1", type="mock", enabled=True),
            FilterConfig(name="filter2", type="mock", enabled=False),
            FilterConfig(name="filter3", type="mock", enabled=True),
        ]
        
        chain = factory.create_filter_chain("test_chain", configs)
        
        assert isinstance(chain, FilterChain)
        assert chain.name == "test_chain"
        assert len(chain) == 2  # Only enabled filters
        assert chain.get_filter_names() == ["filter1", "filter3"]


class TestBasicFilters:
    """Test cases for basic filter implementations."""

    def test_date_range_filter(self, mock_notes):
        """Test DateRangeFilter functionality."""
        config = {
            "start_timestamp": 1000000001000,
            "end_timestamp": 1000000005000,
        }
        filter_instance = DateRangeFilter("date_filter", config)
        result = filter_instance.apply(mock_notes)
        
        # Should include notes with timestamps 1000000001000 to 1000000005000
        assert len(result) == 5  # notes 1, 2, 3, 4, 5

    def test_date_range_filter_no_config(self, mock_notes):
        """Test DateRangeFilter with no configuration."""
        filter_instance = DateRangeFilter("date_filter")
        result = filter_instance.apply(mock_notes)
        assert result == mock_notes

    def test_classification_filter(self, mock_notes):
        """Test ClassificationFilter functionality."""
        config = {"allowed_classifications": ["NOT_MISLEADING"]}
        filter_instance = ClassificationFilter("class_filter", config)
        result = filter_instance.apply(mock_notes)
        
        # Should include only even-indexed notes (0, 2, 4, 6, 8)
        assert len(result) == 5

    def test_summary_length_filter(self, mock_notes):
        """Test SummaryLengthFilter functionality."""
        config = {"min_length": 20, "max_length": 50}
        filter_instance = SummaryLengthFilter("length_filter", config)
        result = filter_instance.apply(mock_notes)
        
        # Filter based on summary length
        expected_count = sum(
            1 for note in mock_notes
            if 20 <= len(note.summary) <= 50
        )
        assert len(result) == expected_count

    def test_believability_filter(self, mock_notes):
        """Test BelievabilityFilter functionality."""
        config = {"require_believable": True}
        filter_instance = BelievabilityFilter("believe_filter", config)
        result = filter_instance.apply(mock_notes)
        
        # Should include only notes where believable == "1" (every 3rd note: 0, 3, 6, 9)
        assert len(result) == 4

    def test_believability_filter_disabled(self, mock_notes):
        """Test BelievabilityFilter with requirement disabled."""
        config = {"require_believable": False}
        filter_instance = BelievabilityFilter("believe_filter", config)
        result = filter_instance.apply(mock_notes)
        assert result == mock_notes