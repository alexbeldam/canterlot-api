from beanie import PydanticObjectId

from canterlot.hoodie import link_id
from canterlot.models import ClubModel, UserModel
from canterlot.types import RoundSelectionMode, RoundStatus
from tools.factories import RoundFactory

SOME_CLUB_ID = PydanticObjectId("507f1f77bcf86cd799439011")
SOME_USER_ID = PydanticObjectId("507f1f77bcf86cd799439012")


def describe_round_model():
    def it_builds_a_valid_round_with_defaults():
        round_ = RoundFactory.build(
            club=ClubModel.link_from_id(SOME_CLUB_ID),
            started_by=UserModel.link_from_id(SOME_USER_ID),
            selection_mode=RoundSelectionMode.RANDOM,
            status=RoundStatus.DECIDED,
        )

        assert link_id(round_.club) == SOME_CLUB_ID
        assert link_id(round_.started_by) == SOME_USER_ID
        assert round_.candidate_pool == []
        assert round_.resolution_method is None
        assert link_id(round_.book) is None
        assert round_.decided_at is None
        assert round_.last_completed_by is None
        assert round_.last_completed_at is None
