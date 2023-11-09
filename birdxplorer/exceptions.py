from .models import ParticipantId


class BaseError(Exception):
    pass


class UserEnrollmentNotFoundError(BaseError):
    def __init__(self, participant_id: ParticipantId):
        super(UserEnrollmentNotFoundError, self).__init__(
            f"User enrollment not found for participant_id={participant_id}"
        )
