from typing import List, Union

from fastapi import APIRouter, Query

from ..models import BaseModel, ParticipantId, Topic, UserEnrollment, Note, NoteId, TweetId
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
    def get_notes(
        note_id: Union[List[NoteId], None] = Query(default=None),
        created_at_from: Union[None, int, str] = Query(default=None),
        created_at_to: Union[None, int, str] = Query(default=None),
        topic_id: Union[List[str], None] = Query(default=None),
        post_id: Union[List[TweetId], None] = Query(default=None),
        language: Union[str, None] = Query(default=None)
    ) -> NoteListResponse:
        filters = {}

        if note_id is not None:
            filters["note_ids"] = note_id
        if created_at_from is not None:
            filters["created_at_from"] = created_at_from
        if created_at_to is not None:
            filters["created_at_to"] = created_at_to
        if topic_id is not None:
            filters["topic_ids"] = topic_id
        if post_id is not None:
            filters["post_ids"] = post_id
        if language is not None:
            filters["language"] = language

        return NoteListResponse(data=list(storage.get_notes(**filters)))

    return router
