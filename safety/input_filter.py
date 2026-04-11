"""Input sanitization — detect and flag prompt injection attempts."""
from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Patterns that indicate prompt injection attempts
INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions|rules|prompts)", re.I),
    re.compile(r"you\s+are\s+now\s+(a|an|the)\s+", re.I),
    re.compile(r"forget\s+(everything|all|your)\s+(you|instructions|rules)", re.I),
    re.compile(r"new\s+instructions?\s*:", re.I),
    re.compile(r"system\s*prompt\s*:", re.I),
    re.compile(r"override\s+(your|all|the)\s+(rules|instructions|safety)", re.I),
    re.compile(r"act\s+as\s+if\s+you\s+(have|had)\s+no\s+(rules|restrictions)", re.I),
    re.compile(r"pretend\s+(you\s+are|to\s+be)\s+", re.I),
    re.compile(r"jailbreak", re.I),
    re.compile(r"DAN\s+mode", re.I),
    re.compile(r"\[INST\]|\[/INST\]|<<SYS>>|<\|im_start\|>", re.I),
]


def check_injection(text: str) -> Optional[str]:
    """Check if text contains prompt injection patterns.
    Returns warning message if suspicious, None if clean."""
    for pattern in INJECTION_PATTERNS:
        match = pattern.search(text)
        if match:
            logger.warning("Potential prompt injection detected: %s", match.group()[:50])
            return f"Suspicious pattern detected: '{match.group()[:30]}...'"
    return None


def sanitize_for_prompt(text: str) -> str:
    """Wrap user content to make injection harder."""
    # Wrap in clear delimiters so the agent knows this is USER CONTENT
    return f"<user_message>\n{text}\n</user_message>"
