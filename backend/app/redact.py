import re

from app.config import Settings


def redact(text: str, settings: Settings | None = None) -> str:
    s = settings or Settings()
    for secret in sorted((v for v in s.secret_values() if len(v) >= 3), key=len, reverse=True):
        text = text.replace(secret, "***")
    return re.sub(r"(?i)\b(password|pwd|uid)\s*=\s*[^;\s]+", r"\1=***", text)
