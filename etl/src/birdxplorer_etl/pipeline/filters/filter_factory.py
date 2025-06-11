"""
Filter factory for creating filters from configuration.

This module provides configuration-driven filter creation, enabling
dynamic filter instantiation based on configuration files.
"""

from __future__ import annotations

from logging import Logger
from typing import Any, Dict, List, Type

from birdxplorer_common.logger import get_logger
from birdxplorer_etl.pipeline.config.models import FilterConfig

from .filter import Filter, FilterError
from .filter_chain import FilterChain


class FilterRegistry:
    """
    Registry for filter types that can be created from configuration.
    
    Maintains a mapping of filter type names to their corresponding classes,
    enabling dynamic filter instantiation based on configuration.
    """

    def __init__(self) -> None:
        """Initialize the filter registry."""
        self._filter_types: Dict[str, Type[Filter]] = {}

    def register(self, filter_type: str, filter_class: Type[Filter]) -> None:
        """
        Register a filter type with its corresponding class.
        
        Args:
            filter_type: String identifier for the filter type
            filter_class: Filter class to register
            
        Raises:
            ValueError: If filter_type is already registered
        """
        if filter_type in self._filter_types:
            raise ValueError(f"Filter type '{filter_type}' is already registered")
        
        if not issubclass(filter_class, Filter):
            raise ValueError(f"Filter class must inherit from Filter base class")
        
        self._filter_types[filter_type] = filter_class

    def unregister(self, filter_type: str) -> bool:
        """
        Unregister a filter type.
        
        Args:
            filter_type: String identifier for the filter type to remove
            
        Returns:
            True if filter type was removed, False if not found
        """
        if filter_type in self._filter_types:
            del self._filter_types[filter_type]
            return True
        return False

    def get_filter_class(self, filter_type: str) -> Type[Filter]:
        """
        Get the filter class for a given type.
        
        Args:
            filter_type: String identifier for the filter type
            
        Returns:
            Filter class for the specified type
            
        Raises:
            ValueError: If filter type is not registered
        """
        if filter_type not in self._filter_types:
            raise ValueError(f"Unknown filter type: '{filter_type}'")
        
        return self._filter_types[filter_type]

    def get_registered_types(self) -> List[str]:
        """
        Get list of all registered filter types.
        
        Returns:
            List of registered filter type names
        """
        return list(self._filter_types.keys())

    def is_registered(self, filter_type: str) -> bool:
        """
        Check if a filter type is registered.
        
        Args:
            filter_type: String identifier for the filter type
            
        Returns:
            True if filter type is registered, False otherwise
        """
        return filter_type in self._filter_types


class FilterFactory:
    """
    Factory for creating filters from configuration.
    
    Creates filter instances and filter chains based on configuration objects,
    enabling flexible and dynamic filter setup.
    """

    def __init__(self, registry: FilterRegistry | None = None, logger: Logger | None = None) -> None:
        """
        Initialize the filter factory.
        
        Args:
            registry: Filter registry to use (creates default if not provided)
            logger: Optional logger instance (creates default if not provided)
        """
        self.registry = registry or FilterRegistry()
        self.logger = logger or get_logger()

    def create_filter(self, config: FilterConfig) -> Filter:
        """
        Create a filter instance from configuration.
        
        Args:
            config: Filter configuration object
            
        Returns:
            Configured filter instance
            
        Raises:
            FilterError: If filter creation fails
        """
        try:
            self.logger.info(f"Creating filter '{config.name}' of type '{config.type}'")
            
            # Get the filter class from registry
            filter_class = self.registry.get_filter_class(config.type)
            
            # Create filter instance with configuration
            filter_instance = self._instantiate_filter(filter_class, config)
            
            self.logger.info(f"Successfully created filter '{config.name}'")
            return filter_instance
            
        except Exception as e:
            error_msg = f"Failed to create filter '{config.name}' of type '{config.type}'"
            self.logger.error(f"{error_msg}: {e}")
            raise FilterError(
                Filter(config.name),  # Create a dummy filter for error reporting
                error_msg,
                e
            )

    def create_filter_chain(self, chain_name: str, filter_configs: List[FilterConfig]) -> FilterChain:
        """
        Create a filter chain from a list of filter configurations.
        
        Args:
            chain_name: Name for the filter chain
            filter_configs: List of filter configurations
            
        Returns:
            Configured filter chain
            
        Raises:
            FilterError: If any filter creation fails
        """
        self.logger.info(f"Creating filter chain '{chain_name}' with {len(filter_configs)} filters")
        
        filters = []
        for config in filter_configs:
            if config.enabled:
                filter_instance = self.create_filter(config)
                filters.append(filter_instance)
            else:
                self.logger.info(f"Skipping disabled filter '{config.name}'")
        
        chain = FilterChain(chain_name, filters, self.logger)
        
        self.logger.info(
            f"Successfully created filter chain '{chain_name}' with {len(filters)} enabled filters"
        )
        
        return chain

    def _instantiate_filter(self, filter_class: Type[Filter], config: FilterConfig) -> Filter:
        """
        Instantiate a filter with the given configuration.
        
        Args:
            filter_class: Filter class to instantiate
            config: Filter configuration
            
        Returns:
            Configured filter instance
            
        Raises:
            Exception: If instantiation fails
        """
        # Try to create filter with config dictionary if constructor supports it
        try:
            # First try: constructor that accepts name and config dict
            return filter_class(config.name, config.config)
        except TypeError:
            try:
                # Second try: constructor that accepts only name
                filter_instance = filter_class(config.name)
                # Try to set configuration if the filter has a configure method
                if hasattr(filter_instance, 'configure'):
                    filter_instance.configure(config.config)
                return filter_instance
            except Exception:
                # Final fallback: just name
                return filter_class(config.name)

    def get_registry(self) -> FilterRegistry:
        """
        Get the filter registry used by this factory.
        
        Returns:
            The filter registry instance
        """
        return self.registry


# Global filter registry instance
_global_registry = FilterRegistry()


def get_global_registry() -> FilterRegistry:
    """
    Get the global filter registry instance.
    
    Returns:
        Global filter registry
    """
    return _global_registry


def register_filter(filter_type: str, filter_class: Type[Filter]) -> None:
    """
    Register a filter type in the global registry.
    
    Args:
        filter_type: String identifier for the filter type
        filter_class: Filter class to register
    """
    _global_registry.register(filter_type, filter_class)