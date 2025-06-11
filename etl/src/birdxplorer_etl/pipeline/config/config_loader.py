"""
Configuration loader for ETL pipeline.

This module provides functionality to load and validate pipeline configurations
from YAML and JSON files, converting them to type-safe configuration objects.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Union

import yaml

from .models import AIConfig, ComponentConfig, ETLConfig, ExtractionConfig, FilterConfig


class ConfigurationError(Exception):
    """Exception raised when configuration loading or validation fails."""

    pass


class ConfigLoader:
    """
    Configuration loader for ETL pipeline.

    Supports loading configurations from YAML and JSON files with
    comprehensive validation and error handling.
    """

    @staticmethod
    def load_from_file(file_path: Union[str, Path]) -> ETLConfig:
        """
        Load configuration from a file.

        Args:
            file_path: Path to the configuration file (YAML or JSON)

        Returns:
            ETLConfig: Parsed and validated configuration object

        Raises:
            ConfigurationError: If file loading or parsing fails
            FileNotFoundError: If the configuration file does not exist
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {file_path}")

        try:
            with open(file_path, "r", encoding="utf-8") as file:
                content = file.read()

            # Determine file format and parse
            if file_path.suffix.lower() in [".yaml", ".yml"]:
                data = yaml.safe_load(content)
            elif file_path.suffix.lower() == ".json":
                data = json.loads(content)
            else:
                # Try to auto-detect format
                try:
                    data = yaml.safe_load(content)
                except yaml.YAMLError:
                    try:
                        data = json.loads(content)
                    except json.JSONDecodeError as e:
                        raise ConfigurationError(f"Unable to parse configuration file as YAML or JSON: {e}")

            return ConfigLoader.load_from_dict(data)

        except (yaml.YAMLError, json.JSONDecodeError) as e:
            raise ConfigurationError(f"Failed to parse configuration file {file_path}: {e}")
        except Exception as e:
            raise ConfigurationError(f"Unexpected error loading configuration from {file_path}: {e}")

    @staticmethod
    def load_from_dict(data: Dict[str, Any]) -> ETLConfig:
        """
        Load configuration from a dictionary.

        Args:
            data: Configuration data as dictionary

        Returns:
            ETLConfig: Parsed and validated configuration object

        Raises:
            ConfigurationError: If validation fails
        """
        try:
            # Validate required fields
            if "pipeline_name" not in data:
                raise ConfigurationError("Missing required field: pipeline_name")

            # Parse components
            components = []
            for comp_data in data.get("components", []):
                if not isinstance(comp_data, dict):
                    raise ConfigurationError(f"Invalid component configuration: {comp_data}")

                components.append(
                    ComponentConfig(
                        name=comp_data.get("name", ""),
                        type=comp_data.get("type", ""),
                        config=comp_data.get("config", {}),
                        enabled=comp_data.get("enabled", True),
                        description=comp_data.get("description"),
                    )
                )

            # Parse filters
            filters = []
            for filter_data in data.get("filters", []):
                if not isinstance(filter_data, dict):
                    raise ConfigurationError(f"Invalid filter configuration: {filter_data}")

                filters.append(
                    FilterConfig(
                        name=filter_data.get("name", ""),
                        type=filter_data.get("type", ""),
                        config=filter_data.get("config", {}),
                        enabled=filter_data.get("enabled", True),
                        description=filter_data.get("description"),
                    )
                )

            # Parse AI settings
            ai_settings = None
            if "ai_settings" in data:
                ai_data = data["ai_settings"]
                if not isinstance(ai_data, dict):
                    raise ConfigurationError(f"Invalid ai_settings configuration: {ai_data}")

                ai_settings = AIConfig(
                    model_name=ai_data.get("model_name", "gpt-3.5-turbo"),
                    temperature=ai_data.get("temperature", 0.7),
                    max_tokens=ai_data.get("max_tokens"),
                    api_key=ai_data.get("api_key"),
                    base_url=ai_data.get("base_url"),
                    timeout=ai_data.get("timeout", 30),
                    retry_attempts=ai_data.get("retry_attempts", 3),
                    config=ai_data.get("config", {}),
                )

            # Parse extraction settings
            extraction_settings = None
            if "extraction_settings" in data:
                ext_data = data["extraction_settings"]
                if not isinstance(ext_data, dict):
                    raise ConfigurationError(f"Invalid extraction_settings configuration: {ext_data}")

                extraction_settings = ExtractionConfig(
                    source_type=ext_data.get("source_type", "database"),
                    connection_string=ext_data.get("connection_string"),
                    batch_size=ext_data.get("batch_size", 1000),
                    max_retries=ext_data.get("max_retries", 3),
                    timeout=ext_data.get("timeout", 300),
                    parallel_jobs=ext_data.get("parallel_jobs", 1),
                    config=ext_data.get("config", {}),
                )

            # Create main configuration
            config = ETLConfig(
                pipeline_name=data["pipeline_name"],
                components=components,
                filters=filters,
                ai_settings=ai_settings,
                extraction_settings=extraction_settings,
                global_config=data.get("global_config", {}),
                description=data.get("description"),
                version=data.get("version", "1.0"),
                enabled=data.get("enabled", True),
            )

            return config

        except ValueError as e:
            raise ConfigurationError(f"Configuration validation error: {e}")
        except Exception as e:
            raise ConfigurationError(f"Unexpected error parsing configuration: {e}")

    @staticmethod
    def save_to_file(config: ETLConfig, file_path: Union[str, Path], format: str = "yaml") -> None:
        """
        Save configuration to a file.

        Args:
            config: Configuration object to save
            file_path: Path where to save the configuration
            format: Output format ('yaml' or 'json')

        Raises:
            ConfigurationError: If saving fails
            ValueError: If format is not supported
        """
        if format.lower() not in ["yaml", "yml", "json"]:
            raise ValueError(f"Unsupported format: {format}. Use 'yaml' or 'json'")

        file_path = Path(file_path)
        data = config.to_dict()

        try:
            with open(file_path, "w", encoding="utf-8") as file:
                if format.lower() in ["yaml", "yml"]:
                    yaml.dump(data, file, default_flow_style=False, indent=2, sort_keys=False)
                else:  # json
                    json.dump(data, file, indent=2, ensure_ascii=False)

        except Exception as e:
            raise ConfigurationError(f"Failed to save configuration to {file_path}: {e}")

    @staticmethod
    def validate_config(config: ETLConfig) -> None:
        """
        Validate a configuration object.

        Args:
            config: Configuration to validate

        Raises:
            ConfigurationError: If validation fails
        """
        try:
            # The ETLConfig.__post_init__ method handles most validation
            # Additional custom validation can be added here
            pass
        except Exception as e:
            raise ConfigurationError(f"Configuration validation failed: {e}")

    @staticmethod
    def create_default_config(pipeline_name: str) -> ETLConfig:
        """
        Create a default configuration.

        Args:
            pipeline_name: Name for the pipeline

        Returns:
            ETLConfig: Default configuration object
        """
        return ETLConfig(
            pipeline_name=pipeline_name,
            components=[
                ComponentConfig(
                    name="default_extractor",
                    type="DataExtractorComponent",
                    description="Default data extractor component",
                ),
                ComponentConfig(
                    name="default_transformer",
                    type="DataTransformerComponent",
                    description="Default data transformer component",
                ),
                ComponentConfig(
                    name="default_loader",
                    type="DataLoaderComponent",
                    description="Default data loader component",
                ),
            ],
            filters=[
                FilterConfig(
                    name="default_filter",
                    type="DataFilterComponent",
                    description="Default data filter",
                ),
            ],
            ai_settings=AIConfig(),
            extraction_settings=ExtractionConfig(),
            description="Default ETL pipeline configuration",
        )


def load_config(file_path: Union[str, Path]) -> ETLConfig:
    """
    Convenience function to load configuration from a file.

    Args:
        file_path: Path to the configuration file

    Returns:
        ETLConfig: Loaded configuration

    Raises:
        ConfigurationError: If loading fails
    """
    return ConfigLoader.load_from_file(file_path)


def create_sample_config(output_path: Union[str, Path], format: str = "yaml") -> None:
    """
    Create a sample configuration file.

    Args:
        output_path: Path where to save the sample configuration
        format: Output format ('yaml' or 'json')
    """
    sample_config = ETLConfig(
        pipeline_name="language_first_pattern",
        description="Sample ETL pipeline configuration",
        components=[
            ComponentConfig(
                name="note_extractor",
                type="NoteExtractorComponent",
                description="Extract notes from data source",
                config={"batch_size": 1000, "timeout": 60},
            ),
            ComponentConfig(
                name="note_language_filter",
                type="LanguageFilterComponent",
                description="Filter notes by language",
                config={"target_languages": ["en", "ja"], "default_language": "en"},
            ),
            ComponentConfig(
                name="note_transformer",
                type="NoteTransformerComponent",
                description="Transform and clean note data",
                config={"remove_duplicates": True, "normalize_text": True},
            ),
        ],
        filters=[
            FilterConfig(
                name="quality_filter",
                type="QualityFilterComponent",
                description="Filter low-quality notes",
                config={"min_length": 10, "max_length": 5000},
            ),
        ],
        ai_settings=AIConfig(
            model_name="gpt-3.5-turbo",
            temperature=0.7,
            max_tokens=2000,
            timeout=30,
        ),
        extraction_settings=ExtractionConfig(
            source_type="database",
            batch_size=500,
            parallel_jobs=2,
            timeout=120,
        ),
    )

    ConfigLoader.save_to_file(sample_config, output_path, format)
