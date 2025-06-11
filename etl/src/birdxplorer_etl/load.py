"""
ETL Load Module - Compatibility Layer

This module provides backward compatibility for the load_data function
while using the new pipeline component architecture under the hood.
"""

import logging

from birdxplorer_etl.pipeline.base.context import PipelineContext
from birdxplorer_etl.pipeline.components import DataLoaderComponent


def load_data():
    """
    Load transformed data to S3 using pipeline components.

    This function maintains compatibility with the original interface
    while leveraging the new component-based architecture.
    """
    logger = logging.getLogger(__name__)
    logger.info("Starting data loading using pipeline components")

    try:
        # Create pipeline context
        context = PipelineContext()

        # Initialize data loader component
        loader = DataLoaderComponent(
            name="data_loader",
            config={
                "input_directory": "./data/transformed",
                "aws_region": "ap-northeast-1",
                "timestamp_format": "%Y-%m-%d %H:%M",
            },
        )

        # Setup and execute loading
        loader.setup(context)
        context = loader.execute(context)

        # Get results from context
        files_uploaded = context.get_metadata("data_loader_files_uploaded", 0)
        bucket_name = context.get_metadata("data_loader_s3_bucket", "N/A")

        if context.get_metadata("data_loader_status") == "skipped":
            logger.info("Data loading skipped - no S3 bucket configured")
        else:
            logger.info(f"Data loading completed successfully. Uploaded {files_uploaded} files to {bucket_name}")

    except Exception as e:
        logger.error(f"Data loading failed: {e}")
        raise
