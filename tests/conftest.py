import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--live", action="store_true", help="also run tests that hit the real clearoutside.com site")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--live"):
        return
    skip_live = pytest.mark.skip(reason="needs --live to run")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)
