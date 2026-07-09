"""Shared helpers for writing generated artifacts to disk or returning them inline.

Phase A goal: keep tool responses compact. When a generator is given an
``output_path`` it writes the artifact to that file and returns a small
``{status, format, path, bytes, summary, warnings}`` response with **no**
``content`` field, so a large netlist/schematic never floods the model context.
When no path is given the full content is returned inline, truncated with a
warning once it exceeds :data:`INLINE_CONTENT_LIMIT`.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

# Inline responses larger than this many characters are truncated, with a
# warning that points at output_path. Sized to stay well within a model's
# context budget while passing through any normal small design untouched.
INLINE_CONTENT_LIMIT = 32_000


def _utf8_len(text: str) -> int:
    """UTF-8 byte length that tolerates lone surrogates so it never raises."""
    return len(text.encode("utf-8", "surrogatepass"))


def resolve_output_path(output_path: str) -> Path:
    """Expand ``~``, absolutize, and create the parent directory for a target file.

    This intentionally does **not** sandbox the destination: absolute paths, ``..``,
    and ``~`` are honored and an existing file is overwritten. This is a local,
    caller-invoked tool (same trust model as any file-write tool), and iterative
    circuit design relies on regenerating artifacts to the same path. The resolved
    absolute path is echoed back in the response so the caller can see where it went.

    Raises:
        ValueError: if the path is empty/whitespace or names an existing directory.
    """
    if output_path is None or not str(output_path).strip():
        raise ValueError("output_path cannot be empty.")
    path = Path(os.path.expanduser(str(output_path))).resolve()
    if path.exists() and path.is_dir():
        raise ValueError(f"output_path '{path}' is a directory; provide a file path.")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def finalize_artifact(
    content: str,
    output_path: str | None,
    *,
    fmt: str,
    summary: dict[str, Any],
    message: str,
    inline_extra: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> dict:
    """Return either a compact path-based response or an inline-content response.

    Args:
        content: the full generated artifact text.
        output_path: destination file, or ``None``/empty to return inline.
        fmt: artifact format label (e.g. ``"kicad_netlist"``, ``"svg"``).
        summary: compact structured summary echoed in both response shapes.
        message: human-readable status message.
        inline_extra: extra top-level keys merged into the *inline* response only
            (used to preserve back-compat keys like ``total_parts``).
        warnings: pre-existing warnings to carry through.

    Returns:
        With ``output_path``: ``{status, format, path, bytes, summary, warnings,
        message}`` and no ``content``. Without: the full ``content`` inline
        (truncated past :data:`INLINE_CONTENT_LIMIT`) plus ``inline_extra``.
        On a write/path error: ``{status: "error", message}``.
    """
    warnings = list(warnings or [])

    # A non-empty output_path (including whitespace-only) is a write request:
    # resolve_output_path validates it and whitespace surfaces as an error rather
    # than silently falling back to inline. Only None / "" mean "return inline".
    if output_path is not None and str(output_path) != "":
        try:
            path = resolve_output_path(output_path)
            # newline="" disables text-mode "\n" -> "\r\n" translation on Windows,
            # so the file is byte-identical to `content` and its size matches the
            # reported `bytes` — netlists/schematics keep their exact line endings.
            path.write_text(content, encoding="utf-8", newline="")
            file_bytes = path.stat().st_size
        except (ValueError, OSError) as e:
            return {"status": "error", "message": str(e)}
        return {
            "status": "ok",
            "format": fmt,
            "path": str(path),
            "bytes": file_bytes,
            "summary": summary,
            "warnings": warnings,
            "message": f"{message} Written to {path}.",
        }

    response: dict[str, Any] = {
        "status": "ok",
        "format": fmt,
        "summary": summary,
        "content": content,
        "message": message,
    }
    if inline_extra:
        response.update(inline_extra)

    if len(content) > INLINE_CONTENT_LIMIT:
        response["content"] = content[:INLINE_CONTENT_LIMIT]
        response["truncated"] = True
        response["bytes"] = _utf8_len(content)
        warnings.append(
            f"Artifact is {len(content)} characters; inline content truncated to "
            f"{INLINE_CONTENT_LIMIT}. Pass output_path to write the full file to disk."
        )
        response["message"] = f"{message} (truncated — pass output_path for the full artifact)"

    response["warnings"] = warnings
    return response
