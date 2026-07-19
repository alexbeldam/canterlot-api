import re
from difflib import SequenceMatcher

ISBN10_LEN = 10
ISBN13_LEN = 13


def normalize_isbn(isbn_str: str) -> str:
    cleaned = re.sub(r"[^0-9Xx]", "", isbn_str)
    if len(cleaned) not in [ISBN10_LEN, ISBN13_LEN]:
        raise ValueError(f"{isbn_str!r} is not a valid ISBN")
    return cleaned.upper()


def normalize_email(email: str) -> str:
    return email.strip().lower()


def make_uppercase(text: str) -> str:
    return text.upper().strip()


def similarity_ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()
