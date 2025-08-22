def clamp_len(s: str, max_len: int) -> str:
    if len(s) <= max_len:
        return s
    return s[:max_len-1] + "…"
