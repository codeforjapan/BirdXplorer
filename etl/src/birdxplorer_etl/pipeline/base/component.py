"""
Abstract base class for pipeline components.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any

from .context import PipelineContext


class PipelineComponent(ABC):
    """
    Abstract base class for all pipeline components.
    
    Pipeline components are the building blocks of the ETL pipeline.
    Each component performs a specific operation on the data and can
    modify the pipeline context.
    """
    
    def __init__(self, name: str, config: Optional[Dict[str, Any]] = None) -> None:
        """
        Initialize the pipeline component.
        
        Args:
            name: Unique name for this component instance
            config: Optional configuration dictionary for the component
        """
        self.name = name
        self.config = config or {}
    
    @abstractmethod
    def execute(self, context: PipelineContext) -> PipelineContext:
        """
        Execute the component's operation.
        
        This method should be implemented by all concrete pipeline components
        to define their specific processing logic.
        
        Args:
            context: The pipeline context containing data and configuration
            
        Returns:
            The modified pipeline context
            
        Raises:
            PipelineComponentError: If the component execution fails
        """
        pass
    
    def validate_config(self) -> None:
        """
        Validate the component's configuration.
        
        This method can be overridden by concrete components to validate
        their specific configuration requirements.
        
        Raises:
            ValueError: If the configuration is invalid
        """
        pass
    
    def setup(self, context: PipelineContext) -> None:
        """
        Setup method called before execute().
        
        This method can be overridden by concrete components to perform
        any necessary initialization or resource setup.
        
        Args:
            context: The pipeline context
        """
        pass
    
    def teardown(self, context: PipelineContext) -> None:
        """
        Teardown method called after execute().
        
        This method can be overridden by concrete components to perform
        any necessary cleanup or resource release.
        
        Args:
            context: The pipeline context
        """
        pass
    
    def get_config_value(self, key: str, default: Any = None) -> Any:
        """
        Get a configuration value for this component.
        
        Args:
            key: Configuration key
            default: Default value if key is not found
            
        Returns:
            The configuration value or default
        """
        return self.config.get(key, default)
    
    def __str__(self) -> str:
        """String representation of the component."""
        return f"{self.__class__.__name__}(name='{self.name}')"
    
    def __repr__(self) -> str:
        """Detailed string representation of the component."""
        return f"{self.__class__.__name__}(name='{self.name}', config={self.config})"


class PipelineComponentError(Exception):
    """
    Exception raised when a pipeline component encounters an error.
    """
    
    def __init__(self, component: PipelineComponent, message: str, cause: Optional[Exception] = None) -> None:
        """
        Initialize the pipeline component error.
        
        Args:
            component: The component that encountered the error
            message: Error message
            cause: Optional underlying exception that caused this error
        """
        self.component = component
        self.cause = cause
        super().__init__(f"Component '{component.name}' error: {message}")