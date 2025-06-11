"""
FilterChain for chaining and executing multiple filters in sequence.

This module provides the FilterChain class that manages the execution of
multiple filters, maintaining proper execution order and comprehensive logging.
"""

from __future__ import annotations

from logging import Logger
from typing import List

from birdxplorer_common.logger import get_logger
from birdxplorer_common.storage import RowNoteRecord

from .filter import Filter, FilterError


class FilterChain:
    """
    Chain of filters that can be executed in sequence.
    
    FilterChain manages the ordered execution of multiple filters,
    providing detailed logging of each stage and maintaining data integrity
    throughout the filtering process.
    """

    def __init__(self, name: str, filters: List[Filter] | None = None, logger: Logger | None = None) -> None:
        """
        Initialize the filter chain.
        
        Args:
            name: Unique name for this filter chain
            filters: List of filters to execute in order
            logger: Optional logger instance (creates default if not provided)
        """
        self.name = name
        self.filters = filters or []
        self.logger = logger or get_logger()

    def add_filter(self, filter_instance: Filter) -> None:
        """
        Add a filter to the end of the chain.
        
        Args:
            filter_instance: Filter to add to the chain
        """
        self.filters.append(filter_instance)

    def insert_filter(self, index: int, filter_instance: Filter) -> None:
        """
        Insert a filter at a specific position in the chain.
        
        Args:
            index: Position to insert the filter at
            filter_instance: Filter to insert
            
        Raises:
            IndexError: If index is out of range
        """
        self.filters.insert(index, filter_instance)

    def remove_filter(self, filter_name: str) -> bool:
        """
        Remove a filter from the chain by name.
        
        Args:
            filter_name: Name of the filter to remove
            
        Returns:
            True if filter was removed, False if not found
        """
        for i, filter_instance in enumerate(self.filters):
            if filter_instance.get_name() == filter_name:
                del self.filters[i]
                return True
        return False

    def get_filter_names(self) -> List[str]:
        """
        Get the names of all filters in the chain.
        
        Returns:
            List of filter names in execution order
        """
        return [filter_instance.get_name() for filter_instance in self.filters]

    def apply(self, notes: List[RowNoteRecord]) -> List[RowNoteRecord]:
        """
        Apply all filters in the chain to the input data.
        
        Executes each filter in sequence, logging the results of each stage
        and providing detailed information about the filtering process.
        
        Args:
            notes: List of RowNoteRecord instances to filter
            
        Returns:
            Filtered list of RowNoteRecord instances
            
        Raises:
            FilterError: If any filter in the chain fails
        """
        if not self.filters:
            self.logger.info(f"FilterChain '{self.name}': No filters configured, returning original data")
            return notes

        current_data = notes
        initial_count = len(current_data)
        
        self.logger.info(
            f"FilterChain '{self.name}': Starting with {initial_count} notes, "
            f"applying {len(self.filters)} filters"
        )

        for i, filter_instance in enumerate(self.filters):
            try:
                input_count = len(current_data)
                self.logger.info(
                    f"FilterChain '{self.name}': Step {i + 1}/{len(self.filters)} - "
                    f"Applying filter '{filter_instance.get_name()}' to {input_count} notes"
                )

                # Apply the filter
                current_data = filter_instance.apply(current_data)
                
                output_count = len(current_data)
                filtered_count = input_count - output_count
                filter_percentage = (filtered_count / input_count * 100) if input_count > 0 else 0

                self.logger.info(
                    f"FilterChain '{self.name}': Filter '{filter_instance.get_name()}' completed - "
                    f"Filtered out {filtered_count} notes ({filter_percentage:.1f}%), "
                    f"{output_count} remaining"
                )

            except Exception as e:
                error_msg = f"Filter '{filter_instance.get_name()}' failed at step {i + 1}"
                self.logger.error(f"FilterChain '{self.name}': {error_msg}: {e}")
                
                if isinstance(e, FilterError):
                    raise e
                else:
                    raise FilterError(filter_instance, error_msg, e)

        final_count = len(current_data)
        total_filtered = initial_count - final_count
        total_percentage = (total_filtered / initial_count * 100) if initial_count > 0 else 0

        self.logger.info(
            f"FilterChain '{self.name}': Completed - "
            f"Total filtered: {total_filtered} notes ({total_percentage:.1f}%), "
            f"{final_count} remaining"
        )

        return current_data

    def clear(self) -> None:
        """Remove all filters from the chain."""
        self.filters.clear()

    def __len__(self) -> int:
        """Get the number of filters in the chain."""
        return len(self.filters)

    def __str__(self) -> str:
        """String representation of the filter chain."""
        return f"FilterChain(name='{self.name}', filters={len(self.filters)})"

    def __repr__(self) -> str:
        """Detailed string representation of the filter chain."""
        filter_names = self.get_filter_names()
        return f"FilterChain(name='{self.name}', filters={filter_names})"