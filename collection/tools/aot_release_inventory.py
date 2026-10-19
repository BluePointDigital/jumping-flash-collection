"""Strict active-namespace inventory check for a complete static-cache release.

Owner-test previews intentionally keep their existing supplemental-cache and
runtime-fallback policy. Call this after the ordinary AOT verifier only when a
release requires the active namespace to contain exactly its audited pairs.
"""
from pathlib import Path, PurePosixPath
import os
import re


_DLL = re.compile(r"(?:seg-(?:kuseg|kseg1)/)?[0-9A-Fa-f]{8}_[0-9A-Fa-f]{8}\.dll\Z")


def _cache_relative_name(name):
    if not isinstance(name, str) or not _DLL.fullmatch(name):
        raise ValueError("Unsafe audited cache DLL path")
    return PurePosixPath(name).as_posix()


def verify_release_cache_inventory(cache_root, namespace, audited_pairs):
    """Require exactly the DLL and sidecars named by the successful AOT audit.

    `cache_root` is the per-game cache directory (the parent of the serial/gcc
    namespace). `audited_pairs` must come from the successful ordinary AOT
    audit. Supplemental cache seeds remain valid for owner-test previews, but a
    complete-release gate rejects them unless they are part of the audit.
    """
    cache_root = Path(cache_root).resolve()
    namespace = PurePosixPath(namespace.as_posix() if isinstance(namespace, Path) else namespace)
    if namespace.is_absolute() or ".." in namespace.parts or not namespace.parts:
        raise ValueError("Unsafe active cache namespace")
    namespace_path = cache_root.joinpath(*namespace.parts)
    current = cache_root
    for part in namespace.parts:
        current = current / part
        if _is_link_or_junction(current):
            raise ValueError("Active cache namespace contains a symlink or junction")
    active = namespace_path.resolve()
    if cache_root not in active.parents:
        raise ValueError("Active cache namespace escapes the per-game cache")
    expected = set()
    expected_casefold = set()
    for pair in audited_pairs:
        dll = _cache_relative_name(pair.get("dll"))
        for name in (dll, str(PurePosixPath(dll).with_suffix(".ranges"))):
            key = name.casefold()
            if key in expected_casefold:
                raise ValueError("AOT audit contains duplicate or case-aliased cache paths")
            expected_casefold.add(key); expected.add(name)
        if pair.get("resident_sha256"):
            resident = str(PurePosixPath(dll).with_suffix(".resident"))
            key = resident.casefold()
            if key in expected_casefold:
                raise ValueError("AOT audit contains duplicate or case-aliased cache paths")
            expected_casefold.add(key); expected.add(resident)

    actual = set(); actual_casefold = set()
    if active.is_dir():
        for directory, directories, filenames in os.walk(active, followlinks=False, onerror=_walk_error):
            parent = Path(directory)
            for name in directories + filenames:
                path = parent / name
                if _is_link_or_junction(path):
                    raise ValueError("Active cache contains a symlink or junction")
            for name in filenames:
                path = parent / name
                if path.suffix.casefold() not in (".dll", ".ranges", ".resident"):
                    continue
                relative = path.relative_to(active).as_posix()
                key = relative.casefold()
                if key in actual_casefold:
                    raise ValueError("Active cache contains duplicate or case-aliased paths")
                actual_casefold.add(key); actual.add(relative)
    if actual != expected:
        missing = len(expected - actual); extra = len(actual - expected)
        raise ValueError(f"Active cache inventory differs from AOT audit ({missing} missing, {extra} extra)")
    return {"audited_dlls": len(audited_pairs), "audited_sidecars": len(expected) - len(audited_pairs)}


def _is_link_or_junction(path):
    path = Path(path)
    is_junction = getattr(path, "is_junction", None)
    return path.is_symlink() or (is_junction is not None and is_junction())


def _walk_error(error):
    raise error
