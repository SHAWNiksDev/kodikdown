from __future__ import annotations

import errno
import os
import sys
import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


@dataclass
class _DirectoryLocks:
    fd: int
    owners: dict[int, str] = field(default_factory=dict)


_directories: dict[Path, _DirectoryLocks] = {}
_mutex = threading.Lock()


def _after_fork() -> None:
    global _mutex
    _mutex = threading.Lock()
    for locks in _directories.values():
        os.close(locks.fd)
    _directories.clear()


if sys.platform != "win32":
    os.register_at_fork(after_in_child=_after_fork)


def _slot(name: str) -> int:
    digest = sha256(name.casefold().encode("utf-8", errors="surrogatepass")).digest()
    return int.from_bytes(digest[:4], "big") & 0x7FFFFFFF


def _set_lock(fd: int, slot: int, *, unlock: bool = False) -> None:
    if sys.platform == "win32":
        os.lseek(fd, slot, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK if unlock else msvcrt.LK_NBLCK, 1)
    else:
        mode = fcntl.LOCK_UN if unlock else fcntl.LOCK_EX | fcntl.LOCK_NB
        fcntl.lockf(fd, mode, 1, slot)


def _try_lock(fd: int, slot: int) -> bool:
    try:
        _set_lock(fd, slot)
    except OSError as exc:
        if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
            return False
        raise
    return True


@contextmanager
def _directory_locks(directory: Path, *, create: bool = False) -> Iterator[_DirectoryLocks | None]:
    directory = directory.resolve()
    with _mutex:
        locks = _directories.get(directory)
        if locks is None:
            try:
                flags = os.O_RDWR | (os.O_CREAT if create else 0)
                fd = os.open(directory / ".kodikdown.lock", flags, 0o666)
            except FileNotFoundError:
                if create:
                    raise
                yield None
                return
            locks = _directories[directory] = _DirectoryLocks(fd)
        try:
            yield locks
        finally:
            # POSIX drops all of our ranges if any descriptor for this file closes.
            # Keep the shared inode in place so other processes always lock the same file.
            if not locks.owners:
                del _directories[directory]
                os.close(locks.fd)


def try_reserve(target: Path) -> bool:
    slot = _slot(target.name)
    with _directory_locks(target.parent, create=True) as locks:
        assert locks is not None
        if slot in locks.owners or not _try_lock(locks.fd, slot):
            return False
        locks.owners[slot] = target.name
        return True


def release(target: Path) -> None:
    slot = _slot(target.name)
    with _directory_locks(target.parent) as locks:
        if locks is not None and locks.owners.get(slot) == target.name:
            _set_lock(locks.fd, slot, unlock=True)
            del locks.owners[slot]


def any_reserved(directory: Path, names: Iterable[str]) -> bool:
    with _directory_locks(directory) as locks:
        if locks is None:
            return False
        for name in names:
            slot = _slot(name)
            if slot in locks.owners or not _try_lock(locks.fd, slot):
                return True
            _set_lock(locks.fd, slot, unlock=True)
        return False
