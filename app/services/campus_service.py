"""Resolve simple location questions against the active map catalog."""

import re
import unicodedata
from difflib import SequenceMatcher


def normalize(text: str) -> str:
    text = "".join(c for c in unicodedata.normalize("NFD", text.lower())
                   if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def location_target(question: str) -> str | None:
    question = normalize(question)
    match = re.fullmatch(
        r"(?:donde (?:esta|queda|se ubica|se encuentra)|ubicacion de|"
        r"muestrame en el mapa|ubica en el mapa) "
        r"(?:(?:el|la) )?(.+?)(?: por favor)?",
        question,
    )
    if not match:
        return None
    target = match[1]
    # Mixed questions still need the document-based answer.
    if re.search(r"\b(y|horario|horarios|requisitos|tramite|tramites|abre|cierra)\b", target):
        return None
    return target


def location_answer(target: str, places: list[dict]) -> str | None:
    matches = {}
    fuzzy = {}
    for place in places:
        name = normalize(place["nombre"])
        names = {name}
        code = re.match(r"^(?:edificio )?(\d{1,2}[a-z]\d{0,2})(?: |$)", name)
        if code:
            names.update((code[1], f"edificio {code[1]}"))
        if target in names:
            matches[place["id"]] = place
        # Allow small spelling mistakes only in complete multiword place names.
        if (len(target.split()) == len(name.split()) > 1
                and not re.search(r"\d", target + name)):
            if SequenceMatcher(None, target, name).ratio() >= 0.92:
                fuzzy[place["id"]] = place
    candidates = matches or fuzzy
    if len(candidates) != 1:
        return None
    place = next(iter(candidates.values()))
    label = re.sub(r"([\\`*_{}\[\]()<>!#])", r"\\\1", place["nombre"])
    return f"Puedes consultar la ubicación de **{label}** en el mapa del campus.\n\n" \
           f"[Ver {label} en el mapa]({place['map_url']})"
