"""Validated temporal intent and parameterized document filtering."""
from dataclasses import dataclass
import json
import re


@dataclass(frozen=True)
class TemporalIntent:
    scope: str = "vigente"
    period: str | None = None

    def __post_init__(self):
        if self.scope not in ("vigente", "historico", "periodo_especifico"):
            raise ValueError("Invalid temporal scope")
        if self.scope == "periodo_especifico":
            if not isinstance(self.period, str) or not re.fullmatch(r"\d{4}-\d{1,2}", self.period):
                raise ValueError("A specific academic period is required")
        elif self.period is not None:
            raise ValueError("Period is only valid for period-specific retrieval")

    def predicate(self):
        statuses = ["vigente"] if self.scope == "vigente" else ["vigente", "historico", "reemplazado"]
        sql = " AND documento_fuente_id IN (SELECT id FROM documentofuente WHERE temporal_status = ANY(%s)"
        parameters = [statuses]
        if self.scope == "vigente":
            sql += (" AND (effective_from IS NULL OR effective_from <= CURRENT_TIMESTAMP)"
                    " AND (effective_to IS NULL OR effective_to >= CURRENT_TIMESTAMP)")
        elif self.scope == "periodo_especifico":
            sql += " AND academic_period = %s"
            parameters.append(self.period)
        return sql + ") ", parameters


def parse_temporal_hyde(value):
    decoded = json.loads(value)
    if not isinstance(decoded, dict):
        raise ValueError("HyDE must return an object")
    passage = decoded.get("hyde_doc")
    if not isinstance(passage, str) or not passage.strip():
        raise ValueError("HyDE passage is required")
    scope = decoded.get("alcance_temporal")
    period = decoded.get("periodo")
    if period is not None and not isinstance(period, str):
        raise ValueError("Period must be text or null")
    intent = TemporalIntent(scope, period or None)
    return intent, passage.strip()
