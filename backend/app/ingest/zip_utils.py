from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path


class ZipSecurityError(RuntimeError):
    pass


def _is_safe_member(name: str) -> bool:
    # Reject absolute paths and traversal
    s = name.replace("\\", "/")
    if s.startswith("/") or ":" in s.split("/")[0]:
        return False
    parts = [p for p in s.split("/") if p not in {"", "."}]
    if any(p == ".." for p in parts):
        return False
    return True


def safe_extract_zip(zip_path: Path, out_dir: Path, max_files: int = 200000, max_total_bytes: int = 10_000_000_000) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    total = 0
    count = 0
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            count += 1
            if count > max_files:
                raise ZipSecurityError(f"Too many files in zip (> {max_files})")
            if not _is_safe_member(info.filename):
                raise ZipSecurityError(f"Unsafe zip member: {info.filename}")
            total += int(info.file_size or 0)
            if total > max_total_bytes:
                raise ZipSecurityError(f"Zip too large when extracted (> {max_total_bytes} bytes)")

        for info in zf.infolist():
            if info.is_dir():
                continue
            member = info.filename.replace("\\", "/")
            dest = out_dir / member
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info, "r") as src, open(dest, "wb") as dst:
                os.fchmod(dst.fileno(), 0o644) if hasattr(os, "fchmod") else None
                while True:
                    buf = src.read(1024 * 1024)
                    if not buf:
                        break
                    dst.write(buf)

