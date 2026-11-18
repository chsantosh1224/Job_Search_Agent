import pytest

from settings import load_config


@pytest.fixture
def cfg():
    return load_config()
