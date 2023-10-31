from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Type, TypeAlias, TypeVar, Union

from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, Field, GetCoreSchemaHandler, TypeAdapter
from pydantic.alias_generators import to_camel
from pydantic_core import core_schema

IncEx: TypeAlias = "set[int] | set[str] | dict[int, IncEx] | dict[str, IncEx] | None"
StrT = TypeVar("StrT", bound="BaseString")
IntT = TypeVar("IntT", bound="BaseInt")


class BaseString(str):
    """
    >>> BaseString("test")
    BaseString('test')
    >>> str(BaseString("test"))
    'test'
    >>> ta = TypeAdapter(BaseString)
    >>> ta.validate_python("test")
    BaseString('test')
    >>> ta.validate_python(1)
    Traceback (most recent call last):
     ...
    pydantic_core._pydantic_core.ValidationError: 1 validation error for function-after[validate(), str]
      Input should be a valid string [type=string_type, input_value=1, input_type=int]
     ...
    >>> ta.dump_json(BaseString("test_test"))
    b'"test_test"'
    >>> BaseString.from_str("test")
    BaseString('test')
    >>> ta.validate_python(BaseString.from_str("test"))
    BaseString('test')
    >>> hash(BaseString("test")) == hash("test")
    True
    >>> ta.validate_python("test　test")
    BaseString('test　test')
    """

    @classmethod
    def _proc_str(cls, s: str) -> str:
        return s

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({super().__repr__()})"

    def __str__(self) -> str:
        return super(BaseString, self).__str__()

    @classmethod
    def __get_pydantic_core_schema__(cls, _source_type: Any, _handler: GetCoreSchemaHandler) -> core_schema.CoreSchema:
        return core_schema.no_info_after_validator_function(
            cls.validate,
            core_schema.str_schema(**cls.__get_extra_constraint_dict__()),
            serialization=core_schema.plain_serializer_function_ser_schema(cls.serialize, when_used="json"),
        )

    @classmethod
    def validate(cls: Type[StrT], v: Any) -> StrT:
        return cls(cls._proc_str(v))

    def serialize(self) -> str:
        return str(self)

    @classmethod
    def __get_extra_constraint_dict__(cls) -> dict[str, Any]:
        return {}

    def __hash__(self) -> int:
        return super(BaseString, self).__hash__()

    @classmethod
    def from_str(cls: Type[StrT], v: str) -> StrT:
        return TypeAdapter(cls).validate_python(v)


class UpperCased64DigitsHexadecimalString(BaseString):
    """
    >>> UpperCased64DigitsHexadecimalString.from_str("test")
    Traceback (most recent call last):
     ...
    pydantic_core._pydantic_core.ValidationError: 1 validation error for function-after[validate(), constrained-str]
      String should match pattern '^[0-9A-F]{64}$' [type=string_pattern_mismatch, input_value='test', input_type=str]
        ...
    >>> UpperCased64DigitsHexadecimalString.from_str("1234567890123456789012345678901234567890123456789012345678901234")
    UpperCased64DigitsHexadecimalString('1234567890123456789012345678901234567890123456789012345678901234')
    """

    @classmethod
    def __get_extra_constraint_dict__(cls) -> dict[str, Any]:
        return dict(super().__get_extra_constraint_dict__(), pattern=r"^[0-9A-F]{64}$")


class BaseInt(int):
    """
    >>> BaseInt(1)
    BaseInt(1)
    >>> int(BaseInt(1))
    1
    >>> ta = TypeAdapter(BaseInt)
    >>> ta.validate_python(1)
    BaseInt(1)
    >>> ta.validate_python("1")
    BaseInt(1)
    >>> ta.dump_json(BaseInt(1))
    b'1'
    >>> BaseInt.from_int(1)
    BaseInt(1)
    >>> ta.validate_python(BaseInt.from_int(1))
    BaseInt(1)
    >>> hash(BaseInt(1)) == hash(1)
    True
    """

    @classmethod
    def _proc_int(cls, i: int) -> int:
        return i

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({super().__repr__()})"

    def __int__(self) -> int:
        return super(BaseInt, self).__int__()

    @classmethod
    def __get_pydantic_core_schema__(cls, _source_type: Any, _handler: GetCoreSchemaHandler) -> core_schema.CoreSchema:
        return core_schema.no_info_after_validator_function(
            cls.validate,
            core_schema.int_schema(**cls.__get_extra_constraint_dict__()),
            serialization=core_schema.plain_serializer_function_ser_schema(cls.serialize, when_used="json"),
        )

    @classmethod
    def validate(cls: Type[IntT], v: Any) -> IntT:
        return cls(cls._proc_int(v))

    def serialize(self) -> int:
        return int(self)

    @classmethod
    def __get_extra_constraint_dict__(cls) -> dict[str, Any]:
        return {}

    def __hash__(self) -> int:
        return super(BaseInt, self).__hash__()

    @classmethod
    def from_int(cls: Type[IntT], v: int) -> IntT:
        return TypeAdapter(cls).validate_python(v)


class BaseBoundedInt(BaseInt, ABC):
    """
    >>> class Under10NaturalNumber(BaseBoundedInt):
    ...   @classmethod
    ...   def max_value(cls) -> int:
    ...     return 9
    ...   @classmethod
    ...   def min_value(cls) -> int:
    ...     return 1
    >>> Under10NaturalNumber.from_int(1)
    Under10NaturalNumber(1)
    >>> Under10NaturalNumber.from_int(0)
    Traceback (most recent call last):
     ...
    pydantic_core._pydantic_core.ValidationError: 1 validation error for function-after[validate(), constrained-int]
      Input should be greater than or equal to 1 [type=greater_than_equal, input_value=0, input_type=int]
     ...
    >>> Under10NaturalNumber.from_int(10)
    Traceback (most recent call last):
     ...
    pydantic_core._pydantic_core.ValidationError: 1 validation error for function-after[validate(), constrained-int]
      Input should be less than or equal to 9 [type=less_than_equal, input_value=10, input_type=int]
     ...
    """

    @classmethod
    @abstractmethod
    def max_value(cls) -> int:
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def min_value(cls) -> int:
        raise NotImplementedError

    @classmethod
    def __get_extra_constraint_dict__(cls) -> dict[str, Any]:
        return dict(super().__get_extra_constraint_dict__(), ge=cls.min_value(), le=cls.max_value())


class TwitterTimestamp(BaseBoundedInt):
    """
    >>> TwitterTimestamp.from_int(1)
    Traceback (most recent call last):
     ...
    pydantic_core._pydantic_core.ValidationError: 1 validation error for function-after[validate(), constrained-int]
      Input should be greater than or equal to 1152921600000 [type=greater_than_equal, input_value=1, input_type=int]
     ...
    >>> TwitterTimestamp.from_int(1288834974657)
    TwitterTimestamp(1288834974657)
    >>> TwitterTimestamp.from_int(int(datetime.now().timestamp() * 1000 + 24 * 60 * 60 * 1000))
    Traceback (most recent call last):
     ...
    pydantic_core._pydantic_core.ValidationError: 1 validation error for function-after[validate(), constrained-int]
     ...
    """

    @classmethod
    def max_value(cls) -> int:
        return int(datetime.utcnow().replace(tzinfo=timezone.utc).timestamp() * 1000)

    @classmethod
    def min_value(cls) -> int:
        return int(datetime(2006, 7, 15, 0, 0, 0, 0, timezone.utc).timestamp() * 1000)


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


class ParticipantId(UpperCased64DigitsHexadecimalString):
    ...


class EnrollmentState(str, Enum):
    new_user = "newUser"
    earned_in = "earnedIn"
    at_risk = "atRisk"
    earned_out_acknowledged = "earnedOutAcknowledged"
    earned_out_no_acknowledge = "earnedOutNoAcknowledge"


UserEnrollmentLastStateChangeTimeStamp = Union[TwitterTimestamp, Literal["0"], Literal["103308100"]]


class UserEnrollment(BaseModel):
    participant_id: ParticipantId
    enrollment_state: EnrollmentState
    successful_rating_needed_to_earn_in: str
    timestamp_of_last_state_change: UserEnrollmentLastStateChangeTimeStamp
    timestamp_of_last_earn_out: str
    modeling_population: str
    modeling_group: str


class NoteId(BaseString):
    """
    >>> NoteId.from_str("test")
    Traceback (most recent call last):
     ...
    pydantic_core._pydantic_core.ValidationError: 1 validation error for function-after[validate(), constrained-str]
      String should match pattern '^[0-9]{19}$' [type=string_pattern_mismatch, input_value='test', input_type=str]
     ...
    >>> NoteId.from_str("1234567890123456789")
    NoteId('1234567890123456789')
    """

    @classmethod
    def __get_extra_constraint_dict__(cls) -> dict[str, Any]:
        return dict(super().__get_extra_constraint_dict__(), pattern=r"^[0-9]{19}$")


class NotesBelievable(str, Enum):
    believable_by_few = "BELIEVABLE_BY_FEW"
    believable_by_many = "BELIEVABLE_BY_MANY"
    empty = ""


class Note(BaseModel):
    note_id: NoteId
    note_author_participant_id: str = Field(pattern=r"^[0-9A-F]{64}$")
    created_at_millis: TwitterTimestamp
    tweet_id: str = Field(pattern=r"^[0-9]{9,19}$")
    believable: NotesBelievable
    summary: str
