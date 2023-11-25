from typing import Dict, List, Union

from birdxplorer.models import ParticipantId, UserEnrollment
from birdxplorer.settings import GlobalSettings, PostgresStorageSettings
from birdxplorer.storage import gen_storage


def test_get_user_enrollment_by_participant_id_returns_data(
    user_enrollment_data_list: List[Dict[str, Union[int, str, float]]],
    user_enrollment_records: int,
    settings_for_test: PostgresStorageSettings,
) -> None:
    s = GlobalSettings()
    s.storage_settings = settings_for_test
    storage = gen_storage(settings=s)
    for data in user_enrollment_data_list:
        pid = ParticipantId.from_str(str(data["participantId"]))
        result = storage.get_user_enrollment_by_participant_id(pid)
        assert isinstance(result, UserEnrollment)
        assert result.participant_id == data["participantId"]
        assert result.enrollment_state == data["enrollmentState"]
        assert result.successful_rating_needed_to_earn_in == data["successfulRatingNeededToEarnIn"]
        assert result.timestamp_of_last_state_change == data["timestampOfLastStateChange"]
        assert result.timestamp_of_last_earn_out == data["timestampOfLastEarnOut"]
        assert result.modeling_population == data["modelingPopulation"]
        assert result.modeling_group == data["modelingGroup"]
