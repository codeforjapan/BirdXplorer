"""
Pipeline Filters

This module contains filtering components for intelligent data processing
and cost optimization.
"""

from .basic_filters import (
    BelievabilityFilter,
    ClassificationFilter,
    DateRangeFilter,
    LanguageFilter,
    SummaryLengthFilter,
)
from .filter import Filter, FilterError
from .filter_chain import FilterChain
from .filter_factory import FilterFactory, FilterRegistry, get_global_registry, register_filter

# Register basic filters in the global registry
register_filter("date_range", DateRangeFilter)
register_filter("language", LanguageFilter)
register_filter("classification", ClassificationFilter)
register_filter("summary_length", SummaryLengthFilter)
register_filter("believability", BelievabilityFilter)

__all__ = [
    # Core filter classes
    "Filter",
    "FilterError",
    "FilterChain",
    "FilterFactory",
    "FilterRegistry",
    # Basic filter implementations
    "DateRangeFilter",
    "LanguageFilter",
    "ClassificationFilter",
    "SummaryLengthFilter",
    "BelievabilityFilter",
    # Registry functions
    "get_global_registry",
    "register_filter",
]
