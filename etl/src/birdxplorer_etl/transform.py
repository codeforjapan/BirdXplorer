"""
ETL Transform Module - Compatibility Layer

This module provides backward compatibility for the transform_data function
while using the new pipeline component architecture under the hood.
"""

import logging

from sqlalchemy.orm import Session

from birdxplorer_etl.pipeline.base.context import PipelineContext
from birdxplorer_etl.pipeline.components import DataTransformerComponent


def transform_data(sqlite: Session, postgresql: Session):
    """
    Transform data using pipeline components.

    This function maintains compatibility with the original interface
    while leveraging the new component-based architecture.

    Args:
        sqlite: SQLite database session
        postgresql: PostgreSQL database session
    """
    logger = logging.getLogger(__name__)
    logger.info("Starting data transformation using pipeline components")

    try:
        # Create pipeline context
        context = PipelineContext()
        context.set_data("sqlite_session", sqlite)
        context.set_data("postgresql_session", postgresql)

        # Initialize data transformer component
        transformer = DataTransformerComponent(
            name="data_transformer",
            config={
                "output_directory": "./data/transformed",
                "batch_size": 1000,
                "topic_seed_file": "./seed/topic_seed.csv",
            },
        )

        # Execute transformation
        logger.info("Transforming data and generating CSV files")
        context = transformer.execute(context)

        # Get results from context
        files_created = context.get_metadata("data_transformer_files_created", [])
        logger.info(f"Data transformation completed successfully. Created {len(files_created)} files")

    except Exception as e:
        logger.error(f"Data transformation failed: {e}")
        raise


# Legacy function aliases for backward compatibility
def write_media_csv(postgresql: Session) -> None:
    """
    Legacy function - use DataTransformerComponent instead.

    This function is deprecated and maintained only for backward compatibility.
    """
    import warnings

    warnings.warn(
        "write_media_csv is deprecated. Use DataTransformerComponent instead.", DeprecationWarning, stacklevel=2
    )

    # Import the legacy implementation
    from birdxplorer_etl.legacy.transform import (
        write_media_csv as legacy_write_media_csv,
    )

    return legacy_write_media_csv(postgresql)


def generate_post_link(postgresql: Session):
    """
    Legacy function - use DataTransformerComponent instead.

    This function is deprecated and maintained only for backward compatibility.
    """
    import warnings

    warnings.warn(
        "generate_post_link is deprecated. Use DataTransformerComponent instead.", DeprecationWarning, stacklevel=2
    )

    # Import the legacy implementation
    from birdxplorer_etl.legacy.transform import (
        generate_post_link as legacy_generate_post_link,
    )

    return legacy_generate_post_link(postgresql)


def generate_note_topic(sqlite: Session):
    """
    Legacy function - use DataTransformerComponent instead.

    This function is deprecated and maintained only for backward compatibility.
    """
    import warnings

    warnings.warn(
        "generate_note_topic is deprecated. Use DataTransformerComponent instead.", DeprecationWarning, stacklevel=2
    )

    # Import the legacy implementation
    from birdxplorer_etl.legacy.transform import (
        generate_note_topic as legacy_generate_note_topic,
    )

    return legacy_generate_note_topic(sqlite)
