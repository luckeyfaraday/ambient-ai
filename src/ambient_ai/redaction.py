"""Local-only secret redaction.

Ambient AI runs always-on over terminal history, so a single leaked
credential is an existential failure. This module replaces brittle one-off
regexes with a higher-recall, still fully-local detector:

1. Assignment/flag/header patterns (``KEY=value``, ``--token value``,
   ``Authorization: Bearer ...``) that redact the *value*.
2. A catalog of high-precision provider token shapes (AWS, GitHub, Slack,
   Google, Stripe, OpenAI, JWTs, PEM private-key blocks).
3. A conservative Shannon-entropy sweep that catches unknown opaque tokens
   without flagging ordinary words, paths, URLs, or git hashes.

Everything here is pure stdlib and never leaves the machine.
"""

from __future__ import annotations

import math
import re
from collections import Counter

REDACTED = "[REDACTED]"

# --- Assignment / flag / header patterns (redact the value, keep the key) ---

_SECRET_ENV_PATTERN = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:TOKEN|API_KEY|SECRET|PASSWORD|PASSWD|PRIVATE_KEY)[A-Z0-9_]*)=([^\s]+)"
)
_SECRET_FLAG_PATTERN = re.compile(
    r"(?i)(--(?:token|api-key|secret|password|passwd|private-key)(?:=|\s+))([^\s]+)"
)
_BEARER_PATTERN = re.compile(r"(?i)(Authorization:\s*Bearer\s+)([^\s'\"\\]+)")

# --- High-precision provider token catalog (redact the whole match) ---

_CATALOG_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                       # AWS access key id
    re.compile(r"\bASIA[0-9A-Z]{16}\b"),                       # AWS temp access key id
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),             # GitHub PAT / OAuth / app
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{60,}\b"),           # GitHub fine-grained PAT
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),           # Slack token
    re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),                 # Google API key
    re.compile(r"\b(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]{16,}\b"),  # Stripe
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),                    # OpenAI-style secret key
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{6,}\b"),  # JWT
    re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"
        r".*?-----END (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----",
        re.DOTALL,
    ),
)

# --- Conservative entropy sweep for unknown opaque tokens ---

_ENTROPY_MIN_LEN = 20
_ENTROPY_BITS_THRESHOLD = 3.5
_TOKEN_SPLIT = re.compile(r"(\s+)")
_SECRETISH_CHARSET = re.compile(r"^[A-Za-z0-9+/_\-=.]+$")
_HEX_ONLY = re.compile(r"^[0-9a-fA-F]+$")
_STRIP_CHARS = "'\"`(),;:[]{}<>"


def shannon_entropy(text: str) -> float:
    """Bits of Shannon entropy per character."""
    if not text:
        return 0.0
    counts = Counter(text)
    length = len(text)
    return -sum((c / length) * math.log2(c / length) for c in counts.values())


def _looks_like_secret(token: str) -> bool:
    if len(token) < _ENTROPY_MIN_LEN:
        return False
    if not _SECRETISH_CHARSET.match(token):
        return False
    if "://" in token or "@" in token:  # URLs, emails, scp targets
        return False
    if _HEX_ONLY.match(token):  # git SHAs, checksums — opaque but not secret
        return False
    if not any(ch.isdigit() for ch in token):  # require digits: rules out dotted paths/words
        return False
    if "/" in token and not any(ch.isdigit() for ch in token.split("/")[-1]):
        return False  # filesystem path, not a token
    return shannon_entropy(token) >= _ENTROPY_BITS_THRESHOLD


def _redact_entropy(text: str) -> str:
    parts = _TOKEN_SPLIT.split(text)
    out: list[str] = []
    for part in parts:
        if not part or part.isspace():
            out.append(part)
            continue
        lead = ""
        trail = ""
        core = part
        while core and core[0] in _STRIP_CHARS:
            lead += core[0]
            core = core[1:]
        while core and core[-1] in _STRIP_CHARS:
            trail = core[-1] + trail
            core = core[:-1]
        if _looks_like_secret(core):
            out.append(f"{lead}{REDACTED}{trail}")
        else:
            out.append(part)
    return "".join(out)


def redact_text(text: str) -> str:
    """Redact secrets from a single line/blob of text, in place of values."""
    text = _SECRET_ENV_PATTERN.sub(rf"\1={REDACTED}", text)
    text = _SECRET_FLAG_PATTERN.sub(rf"\1{REDACTED}", text)
    text = _BEARER_PATTERN.sub(rf"\1{REDACTED}", text)
    for pattern in _CATALOG_PATTERNS:
        text = pattern.sub(REDACTED, text)
    text = _redact_entropy(text)
    return text


def redact_command(command: str) -> str:
    """Backward-compatible alias used by the terminal collector."""
    return redact_text(command)
