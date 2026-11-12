import pytest


@pytest.fixture(autouse=True)
def isolated_media_root(settings, tmp_path):
    """
    Keep generated files out of the repository.

    Creating a department now writes an onboarding guide through the real
    storage backend, so every test that touches a department would leave
    a file behind in `media/`. Pointing MEDIA_ROOT at a per-test
    temporary directory keeps the working tree clean and makes the tests
    order-independent.
    """

    settings.MEDIA_ROOT = tmp_path / "media"

    return settings.MEDIA_ROOT
