from typing import List, Union

from fastapi import APIRouter

from ..models import BaseModel, ParticipantId, Topic, UserEnrollment, Note
from ..storage import Storage


class TopicListResponse(BaseModel):
    data: List[Topic]

class NoteListResponse(BaseModel):
    data: List[Note]


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
        return TopicListResponse(data=list(storage.get_topics()))
    
    @router.get("/notes", response_model=NoteListResponse)
    def get_notes(created_at_from: Union[int, None] = None, created_at_to: Union[int, None] = None, topic_id: Union[str, None] = None, post_id: Union[str, None] = None, language: Union[str, None] = None) -> NoteListResponse:
        return NoteListResponse(data=list(storage.get_notes(created_at_from, created_at_to, topic_id, post_id, language)))

    return router
