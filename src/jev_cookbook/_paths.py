"""Standard-library-only containment checks for local recipe asset paths."""

from __future__ import annotations

from pathlib import Path


class AssetPathError(ValueError):
    """An asset path is absolute, a URL, or resolves (through ``..`` or a symlink) outside its root."""


def resolve_asset_path(path: str | Path, *, root: str | Path) -> Path:
    """Resolve ``path`` (relative to ``root``) to a real file path that must stay inside ``root``.

    Use this, or the ``root=`` argument of the loaders that call it, for any path that comes
    from data such as a fixture ``fields`` value. Absolute paths, drive-qualified paths, URLs,
    and relative paths that leave ``root`` through ``..`` or through a symlink all raise
    :class:`AssetPathError` (a ``ValueError``) before any file is opened. Symlinks are followed
    first and the *real* path is compared to the real ``root``, so a link inside the recipe
    folder that points outside it is refused; ``assets/../assets/a.png`` stays allowed.
    A contained path that does not exist is still returned (resolved), so opening it raises
    ``FileNotFoundError``.
    """
    text = str(path)
    if "://" in text or text.startswith("data:"):
        raise AssetPathError("image_asset requires a local file path, not a URL")
    relative = Path(path)
    if relative.is_absolute() or relative.anchor:
        raise AssetPathError(f"asset path {text!r} must be relative to the recipe folder")
    try:
        base = Path(root).resolve()
        resolved = (base / relative).resolve()
    except (OSError, RuntimeError) as exc:  # symlink loop, unreadable component
        raise AssetPathError(f"asset path {text!r} cannot be resolved") from exc
    if not resolved.is_relative_to(base):
        raise AssetPathError(
            f"asset path {text!r} resolves outside the recipe folder {str(root)!r}"
        )
    return resolved
