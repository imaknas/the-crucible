"""Moving one storage location for a test (conftest.isolated_storage sets
the rest and undoes this at the end of the test)."""

from dataclasses import replace

from app.core.storage import current_storage, set_storage


def point(monkeypatch, **locations) -> str:
    """Use these locations (db_path=…, upload_dir=…, env_path=…) for the rest
    of the test, in the test and in the app it drives; returns the first."""
    from app.main import server

    storage = replace(current_storage(), **{k: str(v) for k, v in locations.items()})
    set_storage(storage)
    monkeypatch.setattr(server.state, "storage", storage)
    return str(next(iter(locations.values())))
