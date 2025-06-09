"""
Pipeline Base Classes

This module contains abstract base classes and core interfaces for 
the pipeline infrastructure.
"""

from .component import PipelineComponent, PipelineComponentError
from .context import PipelineContext

__all__ = [
    "PipelineComponent",
    "PipelineComponentError", 
    "PipelineContext",
]