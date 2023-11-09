from .models import ParticipantId, UserEnrollment
from .settings import GlobalSettings


class Storage:
    def get_user_enrollment_by_participant_id(self, participant_id: ParticipantId) -> UserEnrollment:
        raise NotImplementedError


def gen_storage(settings: GlobalSettings) -> Storage:
    return Storage()
