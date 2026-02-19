from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from random import Random
from typing import (
    Annotated,
    Any,
    Callable,
    Dict,
    Generic,
    List,
    Literal,
    Optional,
    Type,
    TypeAlias,
    TypeVar,
    Union,
)
from uuid import UUID

from pydantic import BaseModel as PydanticBaseModel
from pydantic import (
    ConfigDict,
)
from pydantic import Field as PydanticField
from pydantic import (
    GetCoreSchemaHandler,
    GetJsonSchemaHandler,
    HttpUrl,
    TypeAdapter,
    computed_field,
    model_validator,
)
from pydantic.alias_generators import to_camel
from pydantic.json_schema import JsonSchemaValue
from pydantic.main import IncEx
from pydantic_core import core_schema

StrT = TypeVar("StrT", bound="BaseString")
IntT = TypeVar("IntT", bound="BaseInt")
FloatT = TypeVar("FloatT", bound="BaseFloat")


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


class BinaryBool(str):
    @classmethod
    def __get_pydantic_core_schema__(
        cls: Type["BinaryBool"], _source_type: Any, _handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        return core_schema.no_info_after_validator_function(
            cls.validate,
            core_schema.str_schema(**cls.__get_extra_constraint_dict__()),
            serialization=core_schema.plain_serializer_function_ser_schema(cls.serialize, when_used="json"),
        )

    @classmethod
    def validate(cls: Type["BinaryBool"], v: Any) -> "BinaryBool":
        if v not in ["0", "1"]:
            raise ValueError("Input should be 0 or 1")
        return cls(v)

    @classmethod
    def __get_extra_constraint_dict__(cls: Type["BinaryBool"]) -> dict[str, Any]:
        return {}

    def serialize(self) -> str:
        return str(self)

    @classmethod
    def to_bool(cls: Type["BinaryBool"], v: Any) -> bool:
        if isinstance(v, str):
            if v not in ["0", "1"]:
                raise ValueError("Input should be 0 or 1")
            return v == "1"
        return bool(v)


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


class UpToNineteenDigitsDecimalString(BaseString):
    """
    >>> UpToNineteenDigitsDecimalString.from_str("test")
    Traceback (most recent call last):
     ...
    pydantic_core._pydantic_core.ValidationError: 1 validation error for function-after[validate(), constrained-str]
      String should match pattern '^([0-9]{1,19}|)$' [type=string_pattern_mismatch, input_value='test', input_type=str]
     ...
    >>> UpToNineteenDigitsDecimalString.from_str("1234567890123456789")
    UpToNineteenDigitsDecimalString('1234567890123456789')
    >>> UpToNineteenDigitsDecimalString.from_str("123456789012345678")
    UpToNineteenDigitsDecimalString('123456789012345678')
    """

    @classmethod
    def __get_extra_constraint_dict__(cls) -> dict[str, Any]:
        return dict(super().__get_extra_constraint_dict__(), pattern=r"^([0-9]{1,19}|)$")


class NonEmptyStringMixin(BaseString):
    @classmethod
    def __get_extra_constraint_dict__(cls) -> dict[str, Any]:
        return dict(super().__get_extra_constraint_dict__(), min_length=1)


class TrimmedStringMixin(BaseString):
    @classmethod
    def __get_extra_constraint_dict__(cls) -> dict[str, Any]:
        return dict(super().__get_extra_constraint_dict__(), strip_whitespace=True)


class NonEmptyTrimmedString(TrimmedStringMixin, NonEmptyStringMixin):
    """
    >>> NonEmptyTrimmedString.from_str("test")
    NonEmptyTrimmedString('test')
    >>> NonEmptyTrimmedString.from_str("")
    Traceback (most recent call last):
     ...
    pydantic_core._pydantic_core.ValidationError: 1 validation error for function-after[validate(), constrained-str]
      String should have at least 1 character [type=string_too_short, input_value='', input_type=str]
     ...
    """


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


class BaseLowerBoundedInt(BaseInt, ABC):
    """
    >>> class NaturalNumber(BaseLowerBoundedInt):
    ...   @classmethod
    ...   def min_value(cls) -> int:
    ...     return 1
    >>> NaturalNumber.from_int(1)
    NaturalNumber(1)
    >>> NaturalNumber.from_int(0)
    Traceback (most recent call last):
     ...
    pydantic_core._pydantic_core.ValidationError: 1 validation error for function-after[validate(), constrained-int]
      Input should be greater than or equal to 1 [type=greater_than_equal, input_value=0, input_type=int]
     ...
    """

    @classmethod
    @abstractmethod
    def min_value(cls) -> int:
        raise NotImplementedError

    @classmethod
    def __get_extra_constraint_dict__(cls) -> dict[str, Any]:
        return dict(super().__get_extra_constraint_dict__(), ge=cls.min_value())


class NonNegativeInt(BaseLowerBoundedInt):
    """
    >>> NonNegativeInt.from_int(1)
    NonNegativeInt(1)
    >>> NonNegativeInt.from_int(0)
    NonNegativeInt(0)
    >>> NonNegativeInt.from_int(-1)
    Traceback (most recent call last):
     ...
    pydantic_core._pydantic_core.ValidationError: 1 validation error for function-after[validate(), constrained-int]
      Input should be greater than or equal to 0 [type=greater_than_equal, input_value=-1, input_type=int]
     ...
    """

    @classmethod
    def min_value(cls) -> int:
        return 0


class BaseBoundedInt(BaseLowerBoundedInt):
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
    def __get_extra_constraint_dict__(cls) -> dict[str, Any]:
        return dict(super().__get_extra_constraint_dict__(), le=cls.max_value())


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


class BaseFloat(float):
    """
    >>> BaseFloat(1.0)
    BaseFloat(1.0)
    >>> float(BaseFloat(1.0))
    1.0
    >>> ta = TypeAdapter(BaseFloat)
    >>> ta.validate_python(1.0)
    BaseFloat(1.0)
    >>> ta.validate_python("1.0")
    BaseFloat(1.0)
    >>> ta.dump_json(BaseFloat(1.0))
    b'1.0'
    >>> BaseFloat.from_float(1.0)
    BaseFloat(1.0)
    >>> ta.validate_python(BaseFloat.from_float(1.0))
    BaseFloat(1.0)
    >>> hash(BaseFloat(1.0)) == hash(1.0)
    True
    """

    @classmethod
    def _proc_float(cls, f: float) -> float:
        return f

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({super().__repr__()})"

    def __float__(self) -> float:
        return super(BaseFloat, self).__float__()

    @classmethod
    def __get_pydantic_core_schema__(cls, _source_type: Any, _handler: GetCoreSchemaHandler) -> core_schema.CoreSchema:
        return core_schema.no_info_after_validator_function(
            cls.validate,
            core_schema.float_schema(**cls.__get_extra_constraint_dict__()),
            serialization=core_schema.plain_serializer_function_ser_schema(cls.serialize, when_used="json"),
        )

    @classmethod
    def validate(cls: Type[FloatT], v: Any) -> FloatT:
        return cls(cls._proc_float(v))

    def serialize(self) -> float:
        return float(self)

    @classmethod
    def __get_extra_constraint_dict__(cls) -> dict[str, Any]:
        return {}

    def __hash__(self) -> int:
        return super(BaseFloat, self).__hash__()

    @classmethod
    def from_float(cls: Type[FloatT], v: float) -> FloatT:
        return TypeAdapter(cls).validate_python(v)


class BaseLowerBoundedFloat(BaseFloat, ABC):
    """
    >>> class PositiveFloat(BaseLowerBoundedFloat):
    ...   @classmethod
    ...   def min_value(cls) -> float:
    ...     return 0.0
    >>> PositiveFloat.from_float(0.0)
    PositiveFloat(0.0)
    >>> PositiveFloat.from_float(-0.1)
    Traceback (most recent call last):
     ...
    pydantic_core._pydantic_core.ValidationError: 1 validation error for function-after[validate(), constrained-float]
      Input should be greater than or equal to 0 [type=greater_than_equal, input_value=-0.1, input_type=float]
     ...
    """

    @classmethod
    @abstractmethod
    def min_value(cls) -> float:
        raise NotImplementedError

    @classmethod
    def __get_extra_constraint_dict__(cls) -> dict[str, Any]:
        return dict(super().__get_extra_constraint_dict__(), ge=cls.min_value())


class NonNegativeFloat(BaseLowerBoundedFloat):
    """
    >>> NonNegativeFloat.from_float(0.0)
    NonNegativeFloat(0.0)
    >>> NonNegativeFloat.from_float(-0.1)
    Traceback (most recent call last):
     ...
    pydantic_core._pydantic_core.ValidationError: 1 validation error for function-after[validate(), constrained-float]
      Input should be greater than or equal to 0 [type=greater_than_equal, input_value=-0.1, input_type=float]
     ...
    """

    @classmethod
    def min_value(cls) -> float:
        return 0.0


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
        ensure_ascii: bool = False,
        include: IncEx | None = None,
        exclude: IncEx | None = None,
        context: Any | None = None,
        by_alias: bool | None = True,
        exclude_unset: bool = False,
        exclude_defaults: bool = False,
        exclude_none: bool = False,
        exclude_computed_fields: bool = False,
        round_trip: bool = False,
        warnings: bool | Literal["none", "warn", "error"] = True,
        fallback: Callable[[Any], Any] | None = None,
        serialize_as_any: bool = False,
    ) -> str:
        return super(BaseModel, self).model_dump_json(
            indent=indent,
            ensure_ascii=ensure_ascii,
            include=include,
            exclude=exclude,
            context=context,
            by_alias=by_alias,
            exclude_unset=exclude_unset,
            exclude_defaults=exclude_defaults,
            exclude_none=exclude_none,
            exclude_computed_fields=exclude_computed_fields,
            round_trip=round_trip,
            warnings=warnings,
            fallback=fallback,
            serialize_as_any=serialize_as_any,
        )


class Message(BaseModel):
    message: str


class ParticipantId(UpperCased64DigitsHexadecimalString): ...


class EnrollmentState(str, Enum):
    new_user = "newUser"
    earned_in = "earnedIn"
    at_risk = "atRisk"
    earned_out_acknowledged = "earnedOutAcknowledged"
    earned_out_no_acknowledge = "earnedOutNoAcknowledge"


class ModelingPopulation(str, Enum):
    control = "CORE"
    treatment = "EXPANSION"


UserEnrollmentLastStateChangeTimeStamp = Union[TwitterTimestamp, Literal["0"], Literal["103308100"]]
UserEnrollmentLastEarnOutTimestamp = Union[TwitterTimestamp, Literal["1"]]


class UserEnrollment(BaseModel):
    participant_id: ParticipantId
    enrollment_state: EnrollmentState
    successful_rating_needed_to_earn_in: NonNegativeInt
    timestamp_of_last_state_change: UserEnrollmentLastStateChangeTimeStamp
    timestamp_of_last_earn_out: UserEnrollmentLastEarnOutTimestamp
    modeling_population: ModelingPopulation
    modeling_group: NonNegativeFloat


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


class NotesClassification(str, Enum):
    not_misleading = "NOT_MISLEADING"
    misinformed_or_potentially_misleading = "MISINFORMED_OR_POTENTIALLY_MISLEADING"


class NotesHarmful(str, Enum):
    little_harm = "LITTLE_HARM"
    considerable_harm = "CONSIDERABLE_HARM"
    empty = ""


class NotesValidationDifficulty(str, Enum):
    easy = "EASY"
    challenging = "CHALLENGING"
    empty = ""


class PublicationStatus(str, Enum):
    """Derived publication status for community notes.

    Calculated from NoteRecord.current_status and NoteRecord.has_been_helpfuled:
    - published: current_status = CURRENTLY_RATED_HELPFUL
    - temporarilyPublished: has_been_helpfuled = True AND current_status IN
      (NEEDS_MORE_RATINGS, CURRENTLY_RATED_NOT_HELPFUL)
    - evaluating: current_status = NEEDS_MORE_RATINGS AND has_been_helpfuled = False
    - unpublished: all other cases
    """

    PUBLISHED = "published"
    TEMPORARILY_PUBLISHED = "temporarilyPublished"
    EVALUATING = "evaluating"
    UNPUBLISHED = "unpublished"


class PostId(UpToNineteenDigitsDecimalString): ...


class NoteData(BaseModel):
    """
    This is for validating the original data from notes.csv.
    """

    note_id: NoteId
    note_author_participant_id: ParticipantId
    created_at_millis: TwitterTimestamp
    tweet_id: PostId
    believable: NotesBelievable
    misleading_other: BinaryBool
    misleading_factual_error: BinaryBool
    misleading_manipulated_media: BinaryBool
    misleading_outdated_information: BinaryBool
    misleading_missing_important_context: BinaryBool
    misleading_unverified_claim_as_fact: BinaryBool
    misleading_satire: BinaryBool
    not_misleading_other: BinaryBool
    not_misleading_factually_correct: BinaryBool
    not_misleading_outdated_but_not_when_written: BinaryBool
    not_misleading_clearly_satire: BinaryBool
    not_misleading_personal_opinion: BinaryBool
    trustworthy_sources: BinaryBool
    is_media_note: BinaryBool
    classification: NotesClassification
    harmful: NotesHarmful
    validation_difficulty: NotesValidationDifficulty
    summary: str


class TopicId(NonNegativeInt): ...


class LanguageIdentifier(str, Enum):
    EN = "en"
    ES = "es"
    JA = "ja"
    PT = "pt"
    DE = "de"
    FR = "fr"
    FI = "fi"
    TR = "tr"
    NL = "nl"
    HE = "he"
    IT = "it"
    FA = "fa"
    CA = "ca"
    AR = "ar"
    EL = "el"
    SV = "sv"
    DA = "da"
    RU = "ru"
    PL = "pl"
    OTHER = "other"

    @classmethod
    def normalize(cls, value: str, default: str = "other") -> str:
        try:
            cls(value)
            return value
        except ValueError:
            return default


class TopicLabelString(NonEmptyTrimmedString): ...


TopicLabel: TypeAlias = Dict[LanguageIdentifier, TopicLabelString]


class Topic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    topic_id: Annotated[TopicId, PydanticField(description="トピックの ID")]
    label: Annotated[TopicLabel, PydanticField(description="トピックの言語ごとのラベル")]
    reference_count: Annotated[
        NonNegativeInt, PydanticField(description="このトピックに分類されたコミュニティノートの数")
    ]


class SummaryString(NonEmptyTrimmedString): ...


class NoteStatus(str, Enum):
    """Enum for note status values"""

    NEEDS_MORE_RATINGS = "NEEDS_MORE_RATINGS"
    CURRENTLY_RATED_HELPFUL = "CURRENTLY_RATED_HELPFUL"
    CURRENTLY_RATED_NOT_HELPFUL = "CURRENTLY_RATED_NOT_HELPFUL"


class NoteStatusHistory(BaseModel):
    """Model for note status history entry"""

    status: Annotated[NoteStatus, PydanticField(description="ノートのステータス")]
    date: Annotated[
        TwitterTimestamp, PydanticField(description="ステータス変更日時 (ミリ秒単位の UNIX EPOCH TIMESTAMP)")
    ]


class Note(BaseModel):
    note_id: Annotated[NoteId, PydanticField(description="コミュニティノートの ID")]
    note_author_participant_id: Annotated[
        Optional[ParticipantId], PydanticField(description="コミュニティノートの作成者の Participant ID")
    ]
    post_id: Annotated[PostId, PydanticField(description="コミュニティノートに対応する X の Post の ID")]
    language: Annotated[LanguageIdentifier, PydanticField(description="コミュニティノートの言語")]
    topics: Annotated[List[Topic], PydanticField(description="推定されたコミュニティノートのトピック")]
    summary: Annotated[SummaryString, PydanticField(description="コミュニティノートの本文")]
    current_status: Annotated[
        NoteStatus | None,
        PydanticField(
            description="コミュニティノートの現在の評価状態",
        ),
    ]
    created_at: Annotated[
        TwitterTimestamp, PydanticField(description="コミュニティノートの作成日時 (ミリ秒単位の UNIX EPOCH TIMESTAMP)")
    ]
    has_been_helpfuled: Annotated[
        bool, PydanticField(description="ノートが役立つと評価されたことがあるかどうか", default=False)
    ]
    rate_count: Annotated[NonNegativeInt, PydanticField(description="ノートの総評価数", default=0)]
    helpful_count: Annotated[NonNegativeInt, PydanticField(description="役立つ評価の数", default=0)]
    not_helpful_count: Annotated[NonNegativeInt, PydanticField(description="役立たない評価の数", default=0)]
    somewhat_helpful_count: Annotated[NonNegativeInt, PydanticField(description="やや役立つ評価の数", default=0)]
    current_status_history: Annotated[
        List[NoteStatusHistory], PydanticField(description="ステータス変更履歴", default_factory=list)
    ]


class UserId(UpToNineteenDigitsDecimalString): ...


class UserName(NonEmptyTrimmedString): ...


class XUser(BaseModel):
    user_id: Annotated[UserId, PydanticField(description="X ユーザーの ID")]
    name: Annotated[UserName, PydanticField(description="X ユーザーのスクリーンネーム")]
    profile_image: Annotated[HttpUrl, PydanticField(description="X ユーザーのプロフィール画像の URL")]
    followers_count: Annotated[NonNegativeInt, PydanticField(description="X ユーザーのフォロワー数")]
    following_count: Annotated[NonNegativeInt, PydanticField(description="X ユーザーのフォロー数")]


# ref: https://developer.x.com/en/docs/x-api/data-dictionary/object-model/media
MediaType: TypeAlias = Literal["photo", "video", "animated_gif"]


class Media(BaseModel):
    media_key: Annotated[str, PydanticField(description="X 上でメディアを一意に識別できるキー")]

    type: Annotated[MediaType, PydanticField(description="メディアの種類")]
    url: Annotated[HttpUrl, PydanticField(description="メディアの URL")]
    width: Annotated[NonNegativeInt, PydanticField(description="メディアの幅")]
    height: Annotated[NonNegativeInt, PydanticField(description="メディアの高さ")]


MediaDetails: TypeAlias = List[Media]


class LinkId(UUID):
    """
    >>> LinkId("53dc4ed6-fc9b-54ef-1afa-90f1125098c5")
    LinkId('53dc4ed6-fc9b-54ef-1afa-90f1125098c5')
    >>> LinkId(UUID("53dc4ed6-fc9b-54ef-1afa-90f1125098c5"))
    LinkId('53dc4ed6-fc9b-54ef-1afa-90f1125098c5')
    """

    def __init__(
        self,
        hex: str | None = None,
        int: int | None = None,
    ) -> None:
        if isinstance(hex, UUID):
            hex = str(hex)
        super().__init__(hex, int=int)

    @classmethod
    def from_url(cls, url: HttpUrl) -> "LinkId":
        """
        >>> LinkId.from_url("https://example.com/")
        LinkId('d5d15194-6574-0c01-8f6f-15abd72b2cf6')
        """
        random_number_generator = Random()
        random_number_generator.seed(str(url).encode("utf-8"))
        return LinkId(int=random_number_generator.getrandbits(128))

    @classmethod
    def __get_pydantic_core_schema__(cls, _source_type: Any, _handler: GetCoreSchemaHandler) -> core_schema.CoreSchema:
        return core_schema.union_schema(
            [
                core_schema.is_instance_schema(cls),
                core_schema.no_info_plain_validator_function(cls.validate),
            ],
            serialization=core_schema.plain_serializer_function_ser_schema(
                cls.serialize, info_arg=False, when_used="json"
            ),
        )

    @classmethod
    def __get_pydantic_json_schema__(
        cls, core_schema: core_schema.CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        json_schema = handler(core_schema)
        json_schema = handler.resolve_ref_schema(json_schema)
        # __get_pydantic_core_schema__ に is_instance_schema を追加したが、
        # APIから返却する際の実態は string (uuid) のみである
        # この差分により、openapi specを自動生成する際に不要な anyOf: [] が生成されてしまうのを抑制する
        del json_schema["anyOf"]
        json_schema["type"] = "string"
        json_schema["format"] = "uuid"
        return json_schema

    @classmethod
    def validate(cls, v: Any) -> "LinkId":
        return cls(v)

    def serialize(self) -> str:
        return str(self)


class Link(BaseModel):
    """
    X に投稿された Post 内のリンク情報を正規化して保持するためのモデル。

    t.co に短縮される前の URL ごとに一意な ID を持つ。

    >>> Link.model_validate_json('{"linkId": "d5d15194-6574-0c01-8f6f-15abd72b2cf6", "url": "https://example.com"}')
    Link(link_id=LinkId('d5d15194-6574-0c01-8f6f-15abd72b2cf6'), url=HttpUrl('https://example.com/'))
    >>> Link(url="https://example.com/")
    Link(link_id=LinkId('d5d15194-6574-0c01-8f6f-15abd72b2cf6'), url=HttpUrl('https://example.com/'))
    >>> Link(link_id=UUID("d5d15194-6574-0c01-8f6f-15abd72b2cf6"), url="https://example.com/")
    Link(link_id=LinkId('d5d15194-6574-0c01-8f6f-15abd72b2cf6'), url=HttpUrl('https://example.com/'))
    """  # noqa: E501

    link_id: Annotated[LinkId, PydanticField(description="リンクを識別できる UUID")]
    url: Annotated[HttpUrl, PydanticField(description="リンクが指す URL")]

    @model_validator(mode="before")
    def validate_link_id(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        if "link_id" not in values:
            values["link_id"] = LinkId.from_url(values["url"])
        return values


class Post(BaseModel):
    post_id: Annotated[PostId, PydanticField(description="X の Post の ID")]
    x_user_id: Annotated[UserId, PydanticField(description="Post を投稿したユーザーの ID。`xUser.userId` と同じ")]
    x_user: Annotated[XUser, PydanticField(description="Post を投稿したユーザーの情報")]
    text: Annotated[str, PydanticField(description="Post の本文")]
    media_details: Annotated[
        MediaDetails, PydanticField(default_factory=lambda: [], description="Post に含まれるメディア情報のリスト")
    ]
    created_at: Annotated[
        TwitterTimestamp, PydanticField(description="Post の作成日時 (ミリ秒単位の UNIX EPOCH TIMESTAMP)")
    ]
    aggregated_at: Annotated[
        TwitterTimestamp,
        PydanticField(description="Post の情報がETLで取得された日時 (ミリ秒単位の UNIX EPOCH TIMESTAMP)"),
    ]
    like_count: Annotated[NonNegativeInt, PydanticField(description="Post のいいね数")]
    repost_count: Annotated[NonNegativeInt, PydanticField(description="Post のリポスト数")]
    impression_count: Annotated[NonNegativeInt, PydanticField(description="Post の表示回数")]
    links: Annotated[
        List[Link], PydanticField(default_factory=lambda: [], description="Post に含まれるリンク情報のリスト")
    ]

    @computed_field(description="Post を X 上で表示する URL")  # type: ignore[prop-decorator]
    @property
    def link(self) -> HttpUrl:
        """
        PostのX上でのURLを返す。
        """
        return HttpUrl(f"https://x.com/{self.x_user.name}/status/{self.post_id}")


class PaginationMeta(BaseModel):
    next: Annotated[
        Optional[HttpUrl],
        PydanticField(
            description="次のページのリクエスト用 URL",
        ),
    ] = None
    prev: Annotated[
        Optional[HttpUrl],
        PydanticField(
            description="前のページのリクエスト用 URL",
        ),
    ] = None


T = TypeVar("T")


class GraphListResponse(BaseModel, Generic[T]):
    """Generic response wrapper for graph API endpoints.

    Provides consistent response structure with data array and metadata.
    All graph endpoints return this wrapper with specific data item type.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
    )

    data: List[T] = PydanticField(
        ...,
        description="Array of data items (type varies by endpoint)",
    )

    updated_at: str = PydanticField(
        ...,
        description="Last update timestamp in YYYY-MM-DD format (UTC). Derived from MAX(created_at) of source table.",
        examples=["2025-01-15"],
    )


class DailyNotesCreationDataItem(BaseModel):
    """Daily community note creation counts by publication status.

    Represents a single day's aggregated note creation data.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
    )

    date: str = PydanticField(
        ...,
        description="Date in YYYY-MM-DD format (UTC timezone)",
        examples=["2025-01-15"],
    )

    published: int = PydanticField(
        ...,
        ge=0,
        description="Count of notes with published status on this date",
    )

    evaluating: int = PydanticField(
        ...,
        ge=0,
        description="Count of notes with evaluating status on this date",
    )

    unpublished: int = PydanticField(
        ...,
        ge=0,
        description="Count of notes with unpublished status on this date",
    )

    temporarily_published: int = PydanticField(
        ...,
        ge=0,
        description="Count of notes with temporarily published status on this date",
    )


class DailyPostCountDataItem(BaseModel):
    """Daily post counts within a specified month range.

    Represents post volume for a single day, optionally filtered by
    associated community note status.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
    )

    date: str = PydanticField(
        ...,
        description="Date in YYYY-MM-DD format (UTC timezone)",
        examples=["2025-01-15"],
    )

    post_count: int = PydanticField(
        ...,
        ge=0,
        description="Total number of posts created on this date",
    )

    status: Optional[str] = PydanticField(
        None,
        description="Publication status of associated notes (if status filter applied)",
    )


class MonthlyNoteDataItem(BaseModel):
    """Monthly community note counts with publication rate.

    Aggregates note creation data by month and calculates the percentage
    of notes that achieved published status.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
    )

    month: str = PydanticField(
        ...,
        description="Month in YYYY-MM format",
        examples=["2025-01"],
    )

    published: int = PydanticField(
        ...,
        ge=0,
        description="Count of notes with published status in this month",
    )

    evaluating: int = PydanticField(
        ...,
        ge=0,
        description="Count of notes with evaluating status in this month",
    )

    unpublished: int = PydanticField(
        ...,
        ge=0,
        description="Count of notes with unpublished status in this month",
    )

    temporarily_published: int = PydanticField(
        ...,
        ge=0,
        description="Count of notes with temporarily published status in this month",
    )

    publication_rate: float = PydanticField(
        ...,
        ge=0.0,
        le=1.0,
        description="Ratio of published notes to total notes (0.0 to 1.0). Returns 0.0 if no notes.",
    )


class NoteEvaluationDataItem(BaseModel):
    """Individual note evaluation metrics for moderation review.

    Provides helpfulness ratings and impression counts for individual notes,
    ordered by impression count descending.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
    )

    note_id: str = PydanticField(
        ...,
        description="Unique identifier for the note",
        examples=["1234567890123456789"],
    )

    name: str = PydanticField(
        ...,
        description="Note summary text or first 100 characters",
    )

    helpful_count: int = PydanticField(
        ...,
        ge=0,
        description="Number of helpful ratings received",
    )

    not_helpful_count: int = PydanticField(
        ...,
        ge=0,
        description="Number of not-helpful ratings received",
    )

    impression_count: int = PydanticField(
        ...,
        ge=0,
        description="Number of times the note was displayed",
    )

    status: str = PydanticField(
        ...,
        description="Publication status of the note",
    )


class PostInfluenceDataItem(BaseModel):
    """Individual post engagement metrics for influence analysis.

    Provides engagement counts (reposts, likes, impressions) for individual posts,
    ordered by impression count descending.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
    )

    post_id: str = PydanticField(
        ...,
        description="Unique identifier for the post",
        examples=["1234567890123456789"],
    )

    name: str = PydanticField(
        ...,
        description="Post text or first 100 characters",
    )

    repost_count: int = PydanticField(
        ...,
        ge=0,
        description="Number of reposts/retweets received",
    )

    like_count: int = PydanticField(
        ...,
        ge=0,
        description="Number of likes received",
    )

    impression_count: int = PydanticField(
        ...,
        ge=0,
        description="Number of times the post was displayed",
    )

    status: Optional[str] = PydanticField(
        None,
        description="Publication status of associated note (if status filter applied)",
    )


class TopNoteAccountDataItem(BaseModel):
    """Top accounts by note count with period-over-period comparison.

    Represents an account's note creation activity for a given period,
    ranked by note count descending with change from the previous equivalent period.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
    )

    rank: int = PydanticField(
        ...,
        ge=1,
        description="Rank position (1-based, ordered by note_count descending)",
    )

    username: str = PydanticField(
        ...,
        description="Display name of the account (x_users.name)",
    )

    note_count: int = PydanticField(
        ...,
        ge=0,
        description="Number of notes created by this account in the current period",
    )

    note_count_change: int = PydanticField(
        ...,
        description="Change in note count compared to previous equivalent period (can be negative)",
    )
