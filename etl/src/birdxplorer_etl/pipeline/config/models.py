"""
Configuration data models for ETL pipeline.

This module defines the data structures used for configuration-driven
ETL pipeline execution, supporting both YAML and JSON formats.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ComponentConfig:
    """Configuration for a pipeline component."""

    name: str
    type: str
    config: Dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    description: Optional[str] = None

    def __post_init__(self) -> None:
        """Validate the component configuration."""
        if not self.name:
            raise ValueError("Component name cannot be empty")
        if not self.type:
            raise ValueError("Component type cannot be empty")


@dataclass
class FilterConfig:
    """Configuration for a pipeline filter."""

    name: str
    type: str
    config: Dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    description: Optional[str] = None

    def __post_init__(self) -> None:
        """Validate the filter configuration."""
        if not self.name:
            raise ValueError("Filter name cannot be empty")
        if not self.type:
            raise ValueError("Filter type cannot be empty")


@dataclass
class AIConfig:
    """Configuration for AI model settings."""

    model_name: str = "gpt-3.5-turbo"
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    timeout: int = 30
    retry_attempts: int = 3
    config: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate the AI configuration."""
        if self.temperature < 0 or self.temperature > 2:
            raise ValueError("Temperature must be between 0 and 2")
        if self.max_tokens is not None and self.max_tokens <= 0:
            raise ValueError("Max tokens must be positive")
        if self.timeout <= 0:
            raise ValueError("Timeout must be positive")
        if self.retry_attempts < 0:
            raise ValueError("Retry attempts cannot be negative")


@dataclass
class ExtractionConfig:
    """Configuration for data extraction settings."""

    source_type: str = "database"
    connection_string: Optional[str] = None
    batch_size: int = 1000
    max_retries: int = 3
    timeout: int = 300
    parallel_jobs: int = 1
    config: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate the extraction configuration."""
        if self.batch_size <= 0:
            raise ValueError("Batch size must be positive")
        if self.max_retries < 0:
            raise ValueError("Max retries cannot be negative")
        if self.timeout <= 0:
            raise ValueError("Timeout must be positive")
        if self.parallel_jobs <= 0:
            raise ValueError("Parallel jobs must be positive")


@dataclass
class ETLConfig:
    """Main ETL pipeline configuration."""

    pipeline_name: str
    components: List[ComponentConfig] = field(default_factory=list)
    filters: List[FilterConfig] = field(default_factory=list)
    ai_settings: Optional[AIConfig] = None
    extraction_settings: Optional[ExtractionConfig] = None
    global_config: Dict[str, Any] = field(default_factory=dict)
    description: Optional[str] = None
    version: str = "1.0"
    enabled: bool = True

    def __post_init__(self) -> None:
        """Validate the ETL configuration."""
        if not self.pipeline_name:
            raise ValueError("Pipeline name cannot be empty")

        # Validate unique component names
        component_names = [comp.name for comp in self.components]
        if len(component_names) != len(set(component_names)):
            raise ValueError("Component names must be unique")

        # Validate unique filter names
        filter_names = [filt.name for filt in self.filters]
        if len(filter_names) != len(set(filter_names)):
            raise ValueError("Filter names must be unique")

        # Initialize default configs if not provided
        if self.ai_settings is None:
            self.ai_settings = AIConfig()
        if self.extraction_settings is None:
            self.extraction_settings = ExtractionConfig()

    def get_component_by_name(self, name: str) -> Optional[ComponentConfig]:
        """Get a component configuration by name."""
        for component in self.components:
            if component.name == name:
                return component
        return None

    def get_filter_by_name(self, name: str) -> Optional[FilterConfig]:
        """Get a filter configuration by name."""
        for filter_config in self.filters:
            if filter_config.name == name:
                return filter_config
        return None

    def get_enabled_components(self) -> List[ComponentConfig]:
        """Get list of enabled components."""
        return [comp for comp in self.components if comp.enabled]

    def get_enabled_filters(self) -> List[FilterConfig]:
        """Get list of enabled filters."""
        return [filt for filt in self.filters if filt.enabled]

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary representation."""
        return {
            "pipeline_name": self.pipeline_name,
            "description": self.description,
            "version": self.version,
            "enabled": self.enabled,
            "components": [
                {
                    "name": comp.name,
                    "type": comp.type,
                    "config": comp.config,
                    "enabled": comp.enabled,
                    "description": comp.description,
                }
                for comp in self.components
            ],
            "filters": [
                {
                    "name": filt.name,
                    "type": filt.type,
                    "config": filt.config,
                    "enabled": filt.enabled,
                    "description": filt.description,
                }
                for filt in self.filters
            ],
            "ai_settings": {
                "model_name": self.ai_settings.model_name if self.ai_settings else "gpt-3.5-turbo",
                "temperature": self.ai_settings.temperature if self.ai_settings else 0.7,
                "max_tokens": self.ai_settings.max_tokens if self.ai_settings else None,
                "timeout": self.ai_settings.timeout if self.ai_settings else 30,
                "retry_attempts": self.ai_settings.retry_attempts if self.ai_settings else 3,
                "config": self.ai_settings.config if self.ai_settings else {},
            },
            "extraction_settings": {
                "source_type": self.extraction_settings.source_type if self.extraction_settings else "database",
                "batch_size": self.extraction_settings.batch_size if self.extraction_settings else 1000,
                "max_retries": self.extraction_settings.max_retries if self.extraction_settings else 3,
                "timeout": self.extraction_settings.timeout if self.extraction_settings else 300,
                "parallel_jobs": self.extraction_settings.parallel_jobs if self.extraction_settings else 1,
                "config": self.extraction_settings.config if self.extraction_settings else {},
            },
            "global_config": self.global_config,
        }