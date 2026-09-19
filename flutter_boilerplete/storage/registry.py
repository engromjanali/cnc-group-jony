"""Lets other apps tell storage cleanup which of their StoredFile references
are still in use, without storage importing a specific feature app - keeping
the dependency one-directional (features depend on storage, not back)."""

_referenced_id_providers = []


def register_referenced_ids_provider(fn):
    """Registers `fn() -> Iterable[uuid]`, called during cleanup to protect
    those StoredFile rows from the orphan sweep. Returns `fn`, so it can be
    used as a decorator."""
    _referenced_id_providers.append(fn)
    return fn


def referenced_stored_file_ids():
    ids = set()
    for provider in _referenced_id_providers:
        ids.update(provider())
    return ids
