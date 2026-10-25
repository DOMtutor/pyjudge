import json

from pydomjudge.model import JudgeInstance, SystemCategory, UserRole
from pydomjudge.scripts.default_instance import make_settings
from pydomjudge.scripts.upload import UsersDescription


def _context(instance: JudgeInstance) -> dict:
    categories = instance.team_categories + [SystemCategory.Jury]
    return {"category_by_key": {c.key: c for c in categories}}


def test_default_instance_roundtrip():
    instance = make_settings()
    restored = JudgeInstance.model_validate_json(instance.model_dump_json())
    # Compare serialised form: defaults use tuples where JSON yields lists
    # (see docs/review.md, ClarificationSettings.answers).
    assert restored.model_dump_json() == instance.model_dump_json()
    assert restored.allowed_language_keys is None


def test_example_instance_parses(examples_dir):
    instance = JudgeInstance.model_validate_json(
        (examples_dir / "instance.json").read_text()
    )
    assert [c.key for c in instance.team_categories] == ["participants"]
    assert instance.allowed_language_keys is None


def test_example_users_parse_with_categories(examples_dir):
    instance = JudgeInstance.model_validate_json(
        (examples_dir / "instance.json").read_text()
    )
    description = UsersDescription.model_validate_json(
        (examples_dir / "users.json").read_text(), context=_context(instance)
    )
    users = {user.key: user for user in description.users}
    assert users["admin"].role is UserRole.Admin
    teams = {team.key: team for team in description.teams}
    assert teams["user_team"].members[0] == users["user"]
    assert teams["user_team"].affiliation == description.affiliations[0]
    assert teams["admin_team"].category == SystemCategory.Jury


def test_users_description_json_roundtrip(examples_dir):
    instance = JudgeInstance.model_validate_json(
        (examples_dir / "instance.json").read_text()
    )
    context = _context(instance)
    original = (examples_dir / "users.json").read_text()
    description = UsersDescription.model_validate_json(original, context=context)
    dumped = description.model_dump_json()
    restored = UsersDescription.model_validate_json(dumped, context=context)
    assert restored == description
    assert json.loads(dumped)["teams"]["user_team"]["members"] == ["user"]
