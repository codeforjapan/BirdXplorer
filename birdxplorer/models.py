from datetime import datetime, timezone
from typing import TypeAlias

from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, Field
from pydantic.alias_generators import to_camel

IncEx: TypeAlias = "set[int] | set[str] | dict[int, IncEx] | dict[str, IncEx] | None"


class BaseModel(PydanticBaseModel):
    """
    >>> from unittest.mock import patch
    >>> from uuid import UUID
    >>> import freezegun
    >>> from datetime import timedelta, timezone, datetime
    >>> from pydantic import Field
    >>> class DerivedModel(BaseModel):
    ...   object_name: str
    >>> x = DerivedModel(object_name='test')
    >>> x
    DerivedModel(object_name='test')
    >>> x.model_dump()
    {'object_name': 'test'}
    >>> x.model_dump_json()
    '{"objectName":"test"}'
    >>> DerivedModel.model_validate_json('{"objectName":"test2"}')
    DerivedModel(object_name='test2')
    >>> DerivedModel.model_validate_json('{"object_name":"test3"}')
    DerivedModel(object_name='test3')
    >>> DerivedModel.model_json_schema()
    {'properties': {'objectName': {'title': 'Objectname', 'type': 'string'}}, 'required': ['objectName'], 'title': 'DerivedModel', 'type': 'object'}
    """  # noqa: E501

    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel, validate_assignment=True)

    def model_dump_json(
        self,
        *,
        indent: int | None = None,
        include: IncEx = None,
        exclude: IncEx = None,
        by_alias: bool = True,
        exclude_unset: bool = False,
        exclude_defaults: bool = False,
        exclude_none: bool = False,
        round_trip: bool = False,
        warnings: bool = True,
    ) -> str:
        return super(BaseModel, self).model_dump_json(
            indent=indent,
            include=include,
            exclude=exclude,
            by_alias=by_alias,
            exclude_unset=exclude_unset,
            exclude_defaults=exclude_defaults,
            exclude_none=exclude_none,
            round_trip=round_trip,
            warnings=warnings,
        )


class Message(BaseModel):
    message: str


class UserEnrollment(BaseModel):
    participant_id: str
    enrollment_state: str
    successful_rating_needed_to_earn_in: str
    timestamp_of_last_state_change: str
    timestamp_of_last_earn_out: str
    modeling_population: str
    modeling_group: str


class Notes(BaseModel):
    note_id: str = Field(pattern=r"^[0-9]{19}$")
    note_author_participant_id: str = Field(pattern=r"^[0-9A-F]{64}$")
    created_at_millis: int = Field(
        gt=(int(datetime(2006, 7, 15, 0, 0, 0, 0, timezone.utc).timestamp() * 1000)),
        lt=(int(datetime.now().timestamp() * 1000)),
    )
    tweet_id: str = Field(pattern=r"^[0-9]{9,19}$")
