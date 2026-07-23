from __future__ import annotations

MAX_WORK_PROMPT_BYTES = 64 * 1024
MAX_FILE_REFERENCES = 32


def normalize_optional_text(
    value: object | None,
    *,
    label: str,
    max_characters: int,
) -> str | None:
    """Normalize optional prose and omit values that are blank after normalization."""

    if value is None:
        return None
    normalized = normalize_exact_text(value, label=label)
    if not normalized.strip():
        return None
    if len(normalized) > max_characters:
        raise ValueError(f"{label} exceeds the controller text limit")
    return normalized


def normalize_exact_text(
    value: object,
    *,
    label: str,
    max_utf8_bytes: int | None = None,
    is_nonblank_required: bool = False,
) -> str:
    """Normalize line endings while preserving all other accepted text exactly."""

    if not isinstance(value, str):
        raise ValueError(f"{label} must be text")
    _validate_xml_text(value, label=label)
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    if is_nonblank_required and not normalized.strip():
        raise ValueError(f"{label} must not be blank")
    if max_utf8_bytes is not None and len(normalized.encode("utf-8")) > max_utf8_bytes:
        raise ValueError(f"{label} exceeds the controller text limit")
    return normalized


def _validate_xml_text(value: str, *, label: str) -> None:
    for character in value:
        codepoint = ord(character)
        is_xml_character = (
            codepoint in {0x9, 0xA, 0xD}
            or 0x20 <= codepoint <= 0xD7FF
            or 0xE000 <= codepoint <= 0xFFFD
            or 0x10000 <= codepoint <= 0x10FFFF
        )
        if not is_xml_character:
            raise ValueError(f"{label} contains illegal text character U+{codepoint:04X}")


__all__ = [
    "MAX_FILE_REFERENCES",
    "MAX_WORK_PROMPT_BYTES",
    "normalize_exact_text",
    "normalize_optional_text",
]
