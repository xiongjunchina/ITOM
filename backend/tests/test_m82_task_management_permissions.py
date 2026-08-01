from app.services.permissions import DEFAULT_MATRIX, MODULE_CODES, MODULES, _BUSINESS_VIEW


def test_task_management_modules_are_registered_for_business_navigation():
    expected = {
        "task_development": "开发任务",
        "task_bug": "Bug 修复",
        "task_delegated": "委派任务",
    }
    module_names = {code: name for code, name, _group in MODULES}

    assert expected.items() <= module_names.items()
    assert set(expected) <= MODULE_CODES
    assert set(expected) <= set(_BUSINESS_VIEW)


def test_task_management_default_permissions_match_team_workflow():
    assert "task_bug" not in DEFAULT_MATRIX["requester"]
    assert "task_development" not in DEFAULT_MATRIX["requester"]
    assert "c" in DEFAULT_MATRIX["it_dev"]["task_bug"]
    assert "c" in DEFAULT_MATRIX["it_dev"]["task_delegated"]
    assert "e" in DEFAULT_MATRIX["it_dev_leader"]["task_development"]
    assert "e" in DEFAULT_MATRIX["it_dev_leader"]["task_bug"]
    assert "e" in DEFAULT_MATRIX["it_pdm"]["task_bug"]
