"""
Pipeline execution context for managing shared state and configuration.
"""
from __future__ import annotations

from typing import Any, Dict, Optional
from dataclasses import dataclass, field
from logging import Logger

from birdxplorer_common.logger import get_logger


@dataclass
class PipelineContext:
    """
    Execution context that maintains shared state and configuration
    throughout the pipeline execution.
    
    This class provides a way to pass data, configuration, and resources
    between pipeline components in a type-safe manner.
    """
    
    # Core execution data
    data: Dict[str, Any] = field(default_factory=dict)
    
    # Configuration parameters
    config: Dict[str, Any] = field(default_factory=dict)
    
    # Shared logger instance
    logger: Optional[Logger] = field(default=None)
    
    # Metadata about the pipeline run
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self) -> None:
        """Initialize the context with default logger if not provided."""
        if self.logger is None:
            self.logger = get_logger()
    
    def set_data(self, key: str, value: Any) -> None:
        """Set a data value in the context."""
        self.data[key] = value
    
    def get_data(self, key: str, default: Any = None) -> Any:
        """Get a data value from the context."""
        return self.data.get(key, default)
    
    def set_config(self, key: str, value: Any) -> None:
        """Set a configuration value in the context."""
        self.config[key] = value
    
    def get_config(self, key: str, default: Any = None) -> Any:
        """Get a configuration value from the context."""
        return self.config.get(key, default)
    
    def set_metadata(self, key: str, value: Any) -> None:
        """Set a metadata value in the context."""
        self.metadata[key] = value
    
    def get_metadata(self, key: str, default: Any = None) -> Any:
        """Get a metadata value from the context."""
        return self.metadata.get(key, default)
    
    def copy(self) -> PipelineContext:
        """Create a shallow copy of the context."""
        return PipelineContext(
            data=self.data.copy(),
            config=self.config.copy(),
            logger=self.logger,
            metadata=self.metadata.copy(),
        )