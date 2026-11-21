"""Bounded, deterministic follow-up retrieval without assistant-authored queries."""
import re
import unicodedata


def _is_elliptical(current):
    normalized = "".join(c for c in unicodedata.normalize("NFD", current.casefold())
                         if not unicodedata.combining(c)).strip().lstrip("¿¡")
    return bool(
        re.fullmatch(r"(?:que documentos necesito|what documents do i need)[?!.\s]*", normalized)
        or re.fullmatch(
            r"(?:y |and |what about )(?:los |las |el |la |the )?"
            r"(?:documentos|requisitos|fechas|costos|documents|requirements|dates|costs)[?!.\s]*",
            normalized,
        )
        or re.search(r"\b(?:eso|esa|ese|ellos|ellas|ello|those|them|that)\b", normalized)
        or re.search(r"\b(?:for|about|with) it\b|\bit[?!.\s]*$", normalized)
    )


def contextual_retrieval_question(current, history):
    if not history or not _is_elliptical(current):
        return current
    for item in reversed(history):
        role = item.get("role") if isinstance(item, dict) else item.role
        content = item.get("content") if isinstance(item, dict) else item.content
        if role == "user" and not _is_elliptical(content):
            bounded = content.encode("utf-8")[:4000].decode("utf-8", errors="ignore")
            return bounded + "\n" + current
    return current
