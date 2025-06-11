"""
Basic filter implementations for common filtering operations.

This module provides concrete filter implementations that can be used
for common data filtering scenarios in the ETL pipeline.
"""

from __future__ import annotations

from typing import Any, Dict, List

from birdxplorer_common.storage import RowNoteRecord

from .filter import Filter


class DateRangeFilter(Filter):
    """
    Filter notes based on creation date range.
    
    Filters RowNoteRecord instances to include only those created within
    a specified date range (inclusive).
    """

    def __init__(self, name: str, config: Dict[str, Any] | None = None) -> None:
        """
        Initialize the date range filter.
        
        Args:
            name: Unique name for this filter instance
            config: Configuration dictionary with 'start_timestamp' and 'end_timestamp'
        """
        super().__init__(name)
        self.config = config or {}
        self.start_timestamp = self.config.get("start_timestamp")
        self.end_timestamp = self.config.get("end_timestamp")

    def apply(self, notes: List[RowNoteRecord]) -> List[RowNoteRecord]:
        """
        Apply date range filtering to the notes.
        
        Args:
            notes: List of RowNoteRecord instances to filter
            
        Returns:
            Filtered list containing only notes within the date range
        """
        if not self.start_timestamp and not self.end_timestamp:
            return notes

        filtered_notes = []
        for note in notes:
            timestamp = int(note.created_at_millis)
            
            # Check start timestamp
            if self.start_timestamp and timestamp < self.start_timestamp:
                continue
                
            # Check end timestamp
            if self.end_timestamp and timestamp > self.end_timestamp:
                continue
                
            filtered_notes.append(note)

        return filtered_notes


class LanguageFilter(Filter):
    """
    Filter notes based on language classification.
    
    Filters RowNoteRecord instances to include only those that match
    specified language criteria.
    """

    def __init__(self, name: str, config: Dict[str, Any] | None = None) -> None:
        """
        Initialize the language filter.
        
        Args:
            name: Unique name for this filter instance
            config: Configuration dictionary with 'allowed_languages' list
        """
        super().__init__(name)
        self.config = config or {}
        self.allowed_languages = set(self.config.get("allowed_languages", []))

    def apply(self, notes: List[RowNoteRecord]) -> List[RowNoteRecord]:
        """
        Apply language filtering to the notes.
        
        Args:
            notes: List of RowNoteRecord instances to filter
            
        Returns:
            Filtered list containing only notes in allowed languages
        """
        if not self.allowed_languages:
            return notes

        filtered_notes = []
        for note in notes:
            # Note: RowNoteRecord doesn't have language field directly
            # This is a placeholder implementation - in practice, you might
            # need to join with other tables or use AI classification
            # For now, we'll just return all notes as a placeholder
            filtered_notes.append(note)

        return filtered_notes


class ClassificationFilter(Filter):
    """
    Filter notes based on their classification status.
    
    Filters RowNoteRecord instances to include only those with
    specific classification values.
    """

    def __init__(self, name: str, config: Dict[str, Any] | None = None) -> None:
        """
        Initialize the classification filter.
        
        Args:
            name: Unique name for this filter instance
            config: Configuration dictionary with 'allowed_classifications' list
        """
        super().__init__(name)
        self.config = config or {}
        self.allowed_classifications = set(self.config.get("allowed_classifications", []))

    def apply(self, notes: List[RowNoteRecord]) -> List[RowNoteRecord]:
        """
        Apply classification filtering to the notes.
        
        Args:
            notes: List of RowNoteRecord instances to filter
            
        Returns:
            Filtered list containing only notes with allowed classifications
        """
        if not self.allowed_classifications:
            return notes

        filtered_notes = []
        for note in notes:
            if str(note.classification) in self.allowed_classifications:
                filtered_notes.append(note)

        return filtered_notes


class SummaryLengthFilter(Filter):
    """
    Filter notes based on summary text length.
    
    Filters RowNoteRecord instances to include only those with
    summaries within specified length bounds.
    """

    def __init__(self, name: str, config: Dict[str, Any] | None = None) -> None:
        """
        Initialize the summary length filter.
        
        Args:
            name: Unique name for this filter instance
            config: Configuration dictionary with 'min_length' and 'max_length'
        """
        super().__init__(name)
        self.config = config or {}
        self.min_length = self.config.get("min_length", 0)
        self.max_length = self.config.get("max_length", float("inf"))

    def apply(self, notes: List[RowNoteRecord]) -> List[RowNoteRecord]:
        """
        Apply summary length filtering to the notes.
        
        Args:
            notes: List of RowNoteRecord instances to filter
            
        Returns:
            Filtered list containing only notes with appropriate summary lengths
        """
        filtered_notes = []
        for note in notes:
            summary_length = len(note.summary) if note.summary else 0
            
            if self.min_length <= summary_length <= self.max_length:
                filtered_notes.append(note)

        return filtered_notes


class BelievabilityFilter(Filter):
    """
    Filter notes based on believability ratings.
    
    Filters RowNoteRecord instances to include only those with
    specific believability values.
    """

    def __init__(self, name: str, config: Dict[str, Any] | None = None) -> None:
        """
        Initialize the believability filter.
        
        Args:
            name: Unique name for this filter instance
            config: Configuration dictionary with 'require_believable' boolean
        """
        super().__init__(name)
        self.config = config or {}
        self.require_believable = self.config.get("require_believable", False)

    def apply(self, notes: List[RowNoteRecord]) -> List[RowNoteRecord]:
        """
        Apply believability filtering to the notes.
        
        Args:
            notes: List of RowNoteRecord instances to filter
            
        Returns:
            Filtered list containing only notes matching believability criteria
        """
        if not self.require_believable:
            return notes

        filtered_notes = []
        for note in notes:
            # Convert BinaryBool to boolean
            is_believable = str(note.believable) == "1"
            
            if is_believable:
                filtered_notes.append(note)

        return filtered_notes