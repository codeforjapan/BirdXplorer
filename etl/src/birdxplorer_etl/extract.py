"""
ETL Extract Module - Compatibility Layer

This module provides backward compatibility for the extract_data function
while using the new pipeline component architecture under the hood.
"""

import logging
from sqlalchemy.orm import Session

from birdxplorer_etl.pipeline.base.context import PipelineContext
from birdxplorer_etl.pipeline.components import NoteExtractorComponent, PostExtractorComponent


def extract_data(sqlite: Session, postgresql: Session):
    """
    Extract community notes and post data using pipeline components.
    
    This function maintains compatibility with the original interface
    while leveraging the new component-based architecture.
    
    Args:
        sqlite: SQLite database session
        postgresql: PostgreSQL database session
    """
    logger = logging.getLogger(__name__)
    logger.info("Starting data extraction using pipeline components")
    
    try:
        # Create pipeline context
        context = PipelineContext()
        context.set_data("sqlite_session", sqlite)
        context.set_data("postgresql_session", postgresql)
        
        # Initialize note extractor component
        note_extractor = NoteExtractorComponent(
            name="note_extractor",
            config={
                "community_note_days_ago": 3,  # Default from settings
                "use_dummy_data": False
            }
        )
        
        # Initialize post extractor component  
        post_extractor = PostExtractorComponent(
            name="post_extractor",
            config={}
        )
        
        # Execute note extraction
        logger.info("Extracting community notes data")
        context = note_extractor.execute(context)
        
        # Execute post extraction
        logger.info("Extracting post data for notes")
        context = post_extractor.execute(context)
        
        logger.info("Data extraction completed successfully")
        
    except Exception as e:
        logger.error(f"Data extraction failed: {e}")
        raise