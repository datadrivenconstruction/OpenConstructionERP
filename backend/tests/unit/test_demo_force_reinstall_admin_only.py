from app.core.demo_marker import force_reinstall_allowed


def test_force_reinstall_needs_admin():
    assert not force_reinstall_allowed("editor", True)
    assert not force_reinstall_allowed(None, True)
    assert force_reinstall_allowed("admin", True)
    assert force_reinstall_allowed("viewer", False)
