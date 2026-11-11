from pydantic import TypeAdapter

from canterlot.types import ClubSlugStr, NormalizedEmailStr, UsernameStr
from tools.factories import ClubFactory, UserFactory

BUILDS = 5000


def describe_user_factory():
    def it_builds_distinct_usernames_that_satisfy_the_username_type():
        adapter = TypeAdapter(UsernameStr)

        usernames = [UserFactory.build().username for _ in range(BUILDS)]

        assert len(set(usernames)) == BUILDS
        for username in usernames:
            assert adapter.validate_python(username) == username

    def it_builds_distinct_emails_that_satisfy_the_normalized_email_type():
        adapter = TypeAdapter(NormalizedEmailStr)

        emails = [UserFactory.build().email for _ in range(BUILDS)]

        assert len(set(emails)) == BUILDS
        for email in emails:
            assert adapter.validate_python(email) == email
            assert email == email.lower()


def describe_club_factory():
    def it_builds_distinct_slugs_that_satisfy_the_slug_type():
        adapter = TypeAdapter(ClubSlugStr)

        slugs = [ClubFactory.build().slug for _ in range(BUILDS)]

        assert len(set(slugs)) == BUILDS
        for slug in slugs:
            assert adapter.validate_python(slug) == slug
