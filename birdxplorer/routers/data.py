from typing import List

from fastapi import APIRouter

from ..models import BaseModel, ParticipantId, Topic, UserEnrollment
from ..storage import Storage


class TopicListResponse(BaseModel):
    data: List[Topic]


def gen_router(storage: Storage) -> APIRouter:
    router = APIRouter()

    @router.get("/user-enrollments/{participant_id}", response_model=UserEnrollment)
    def get_user_enrollment_by_participant_id(participant_id: ParticipantId) -> UserEnrollment:
        res = storage.get_user_enrollment_by_participant_id(participant_id=participant_id)
        if res is None:
            raise ValueError(f"participant_id={participant_id} not found")
        return res

    @router.get("/topics", response_model=TopicListResponse)
    def get_topics() -> TopicListResponse:
        return TopicListResponse(
            data=[
                Topic(topic_id=1, label={"en": "topic1", "ja": "トピック1"}, reference_count=12341),
                Topic(topic_id=2, label={"en": "topic2", "ja": "トピック2"}, reference_count=1232312342),
                Topic(topic_id=3, label={"en": "topic3", "ja": "トピック3"}, reference_count=3),
            ]
        )

    return router
