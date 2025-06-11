"""
Abstract base class for data filtering in ETL pipeline.

This module provides the foundational Filter class that enables efficient
filtering of Community Notes data with logging and type safety.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, TypeVar

from birdxplorer_common.storage import RowNoteRecord

T = TypeVar("T")


class Filter(ABC):
    """
    Abstract base class for filtering Community Notes data.
    
    Filters are used to process and refine datasets based on specific criteria,
    enabling data quality control and selective processing in the ETL pipeline.
    
    All concrete filter implementations must implement the apply method to define
    their specific filtering logic.
    """

    def __init__(self, name: str) -> None:
        """
        Initialize the filter with a unique name.
        
        Args:
            name: Unique identifier for this filter instance
        """
        self.name = name

    @abstractmethod
    def apply(self, notes: List[RowNoteRecord]) -> List[RowNoteRecord]:
        """
        Apply the filter to a list of RowNoteRecord instances.
        
        This method should be implemented by all concrete filter classes
        to define their specific filtering logic.
        
        Args:
            notes: List of RowNoteRecord instances to filter
            
        Returns:
            Filtered list of RowNoteRecord instances
            
        Raises:
            FilterError: If the filtering operation fails
        """
        pass

    def get_name(self) -> str:
        """
        Get the filter's unique name.
        
        Returns:
            The filter's name
        """
        return self.name

    def __str__(self) -> str:
        """String representation of the filter."""
        return f"{self.__class__.__name__}(name='{self.name}')"

    def __repr__(self) -> str:
        """Detailed string representation of the filter."""
        return f"{self.__class__.__name__}(name='{self.name}')"


class FilterError(Exception):
    """
    Exception raised when a filter encounters an error during processing.
    
    This exception provides context about which filter failed and why,
    facilitating debugging and error handling in filter chains.
    """

    def __init__(self, filter_instance: Filter, message: str, cause: Exception | None = None) -> None:
        """
        Initialize the filter error.
        
        Args:
            filter_instance: The filter that encountered the error
            message: Error message describing what went wrong
            cause: Optional underlying exception that caused this error
        """
        self.filter = filter_instance
        self.cause = cause
        super().__init__(f"Filter '{filter_instance.name}' error: {message}")