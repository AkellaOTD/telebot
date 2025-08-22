from app.config import settings

def has_bad_words(text: str) -> bool:
    words = [w.strip().lower() for w in settings.BAD_WORDS]
    t = text.lower()
    return any(w and w in t for w in words)
