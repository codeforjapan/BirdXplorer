# ETL Pipeline Components

## Overview

This document describes the new component-based ETL pipeline architecture implemented for BirdXplorer. The pipeline components provide a modular, configurable approach to ETL processing while maintaining full backward compatibility.

## Architecture

### Pipeline Components

The ETL pipeline consists of four main components:

1. **NoteExtractorComponent** - Extracts Community Notes data from Twitter's public data repository
2. **PostExtractorComponent** - Extracts X (Twitter) API post data for notes
3. **DataTransformerComponent** - Transforms data and generates CSV files with AI processing
4. **DataLoaderComponent** - Uploads transformed data to S3

### Base Classes

- **PipelineComponent** - Abstract base class for all pipeline components
- **PipelineContext** - Shared execution context for passing data between components
- **PipelineComponentError** - Exception class for component errors

## Components Detail

### NoteExtractorComponent

**Purpose**: Downloads Community Notes data from Twitter's public data repository.

**Configuration Options**:
- `community_note_days_ago`: Number of days to go back for data extraction (default: 3)
- `use_dummy_data`: Whether to use sample data instead of live data (default: false)

**Example Usage**:
```python
from birdxplorer_etl.pipeline.components import NoteExtractorComponent
from birdxplorer_etl.pipeline.base.context import PipelineContext

# Create component
note_extractor = NoteExtractorComponent(
    name="note_extractor",
    config={
        "community_note_days_ago": 5,
        "use_dummy_data": False
    }
)

# Setup context with database sessions
context = PipelineContext()
context.set_data("sqlite_session", sqlite_session)
context.set_data("postgresql_session", postgresql_session)

# Execute
context = note_extractor.execute(context)
```

### PostExtractorComponent

**Purpose**: Extracts X API post data for notes within a specified time range.

**Configuration Options**:
- `target_start_unix_millisecond`: Start time for post extraction
- `target_end_unix_millisecond`: End time for post extraction

**Example Usage**:
```python
from birdxplorer_etl.pipeline.components import PostExtractorComponent

post_extractor = PostExtractorComponent(
    name="post_extractor",
    config={
        "target_start_unix_millisecond": 1640995200000,
        "target_end_unix_millisecond": 1641081600000
    }
)

context = post_extractor.execute(context)
```

### DataTransformerComponent

**Purpose**: Transforms raw database records into CSV files with AI-based language detection and topic estimation.

**Configuration Options**:
- `output_directory`: Directory for CSV output files (default: "./data/transformed")
- `batch_size`: Number of records to process in each batch (default: 1000)
- `topic_seed_file`: Path to topic seed CSV file (default: "./seed/topic_seed.csv")
- `target_start_unix_millisecond`: Start time for filtering records
- `target_end_unix_millisecond`: End time for filtering records

**Generated Files**:
- `note.csv` - Note data with AI language detection
- `post.csv` - Post data
- `user.csv` - User data
- `media.csv` - Media data
- `post_media_association.csv` - Post-media associations
- `post_link.csv` - Link data
- `post_link_association.csv` - Post-link associations
- `topic.csv` - Topic data
- `note_topic_association.csv` - Note-topic associations with AI

**Example Usage**:
```python
from birdxplorer_etl.pipeline.components import DataTransformerComponent

transformer = DataTransformerComponent(
    name="data_transformer",
    config={
        "output_directory": "./output",
        "batch_size": 500,
        "topic_seed_file": "./seed/topics.csv"
    }
)

context = transformer.execute(context)
```

### DataLoaderComponent

**Purpose**: Uploads transformed CSV files to Amazon S3.

**Configuration Options**:
- `s3_bucket_name`: S3 bucket name for uploads
- `aws_region`: AWS region (default: "ap-northeast-1")
- `input_directory`: Directory containing CSV files (default: "./data/transformed")
- `timestamp_format`: Format for S3 object prefix timestamp (default: "%Y-%m-%d %H:%M")
- `file_patterns`: List of file patterns to upload (defaults to standard CSV files)

**Example Usage**:
```python
from birdxplorer_etl.pipeline.components import DataLoaderComponent

loader = DataLoaderComponent(
    name="data_loader",
    config={
        "s3_bucket_name": "my-etl-bucket",
        "aws_region": "us-east-1",
        "input_directory": "./data/transformed"
    }
)

# Setup is required for S3 client initialization
loader.setup(context)
context = loader.execute(context)
```

## Backward Compatibility

### Legacy Migration Strategy

The original ETL functions remain available but now use the component architecture internally:

1. **Legacy Files Preserved**: Original code moved to `legacy/` directory
2. **Compatibility Layer**: Main ETL files (`extract.py`, `transform.py`, `load.py`) now wrap components
3. **Same Interface**: Existing code continues to work without modifications
4. **Deprecation Warnings**: Legacy individual functions show deprecation warnings

### Migration Path

Existing code using the ETL functions will continue to work:

```python
# This still works exactly as before
from birdxplorer_etl.extract import extract_data
from birdxplorer_etl.transform import transform_data
from birdxplorer_etl.load import load_data

sqlite = init_sqlite()
postgresql = init_postgresql()

extract_data(sqlite, postgresql)  # Now uses components internally
transform_data(sqlite, postgresql)  # Now uses components internally
load_data()  # Now uses components internally
```

For new code, use components directly:

```python
from birdxplorer_etl.pipeline.components import (
    NoteExtractorComponent,
    PostExtractorComponent,
    DataTransformerComponent,
    DataLoaderComponent
)
from birdxplorer_etl.pipeline.base.context import PipelineContext

# Create context
context = PipelineContext()
context.set_data("sqlite_session", sqlite_session)
context.set_data("postgresql_session", postgresql_session)

# Configure and run components
components = [
    NoteExtractorComponent("note_extractor", {"community_note_days_ago": 3}),
    PostExtractorComponent("post_extractor", {}),
    DataTransformerComponent("transformer", {"batch_size": 1000}),
    DataLoaderComponent("loader", {"s3_bucket_name": "my-bucket"})
]

# Execute pipeline
for component in components:
    component.setup(context)
    context = component.execute(context)
    component.teardown(context)
```

## Configuration-Driven Pipelines

The component architecture supports configuration-driven pipeline execution using YAML or JSON configuration files:

```yaml
pipeline_name: "etl_pipeline"
description: "BirdXplorer ETL Pipeline"

components:
  - name: "note_extractor"
    type: "NoteExtractorComponent"
    config:
      community_note_days_ago: 3
      use_dummy_data: false
    
  - name: "post_extractor"
    type: "PostExtractorComponent"
    config: {}
    
  - name: "data_transformer"
    type: "DataTransformerComponent"
    config:
      output_directory: "./data/transformed"
      batch_size: 1000
      
  - name: "data_loader"
    type: "DataLoaderComponent"
    config:
      s3_bucket_name: "birdxplorer-etl"
      aws_region: "ap-northeast-1"

ai_settings:
  model_name: "gpt-3.5-turbo"
  temperature: 0.7
  
extraction_settings:
  batch_size: 1000
  parallel_jobs: 1
```

## Testing

Comprehensive tests are available for all components:

- **Component Tests**: `tests/test_etl_components.py`
- **Pipeline Tests**: `tests/test_pipeline_component.py`
- **Context Tests**: `tests/test_pipeline_context.py`
- **Configuration Tests**: `tests/test_config_loader.py`, `tests/test_config_models.py`

Run tests with:
```bash
cd etl
tox  # Runs all tests with formatting, linting, and type checking
```

## Error Handling

All components use structured error handling with `PipelineComponentError`:

```python
try:
    context = component.execute(context)
except PipelineComponentError as e:
    print(f"Component {e.component.name} failed: {e}")
    if e.cause:
        print(f"Underlying cause: {e.cause}")
```

## Performance Considerations

- **Batch Processing**: All components support configurable batch sizes
- **Memory Management**: Large datasets are processed in chunks
- **Database Sessions**: Efficient use of SQLite and PostgreSQL sessions
- **AI Service**: Language detection and topic estimation use cached AI services
- **S3 Uploads**: Files are uploaded individually with proper error handling

## Future Enhancements

The component architecture enables future enhancements:

1. **Parallel Processing**: Components can be enhanced to support parallel execution
2. **Retry Logic**: Built-in retry mechanisms for transient failures
3. **Monitoring**: Integration with monitoring and alerting systems
4. **Custom Components**: Easy addition of new component types
5. **Pipeline Orchestration**: Integration with workflow orchestrators like Airflow
6. **Data Validation**: Built-in data quality checks and validation