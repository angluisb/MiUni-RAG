from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.core.config import Config


class HistoryMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)

    @field_validator("content")
    @classmethod
    def bounded_content(cls, value):
        if not value.strip() or len(value.encode("utf-8")) > 4000:
            raise ValueError("History content must be nonempty and at most 4000 UTF-8 bytes")
        return value


class ScheduleEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: str = Field(max_length=200)
    day: int = Field(ge=1, le=7, strict=True)
    start: str = Field(max_length=30)
    end: str = Field(max_length=30)
    room: str | None = Field(default=None, max_length=200)
    teacher: str | None = Field(default=None, max_length=200)


class PersonalContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schedule: list[ScheduleEntry] = Field(default_factory=list, max_length=100)
    campus_now: str = Field(max_length=60)


class QueryRequest(BaseModel):
    question: str = Field(min_length=1)
    history: list[HistoryMessage] = Field(default_factory=list, max_length=128)
    personal_context: PersonalContext | None = None

    @model_validator(mode="after")
    def completed_bounded_history(self):
        if len(self.history) % 2 or any(
            item.role != ("user" if index % 2 == 0 else "assistant")
            for index, item in enumerate(self.history)
        ):
            raise ValueError("History must contain completed alternating user/assistant turns")
        if sum(len(item.content.encode("utf-8")) for item in self.history) > 64000:
            raise ValueError("History wire budget exceeded")
        while len(self.history) > Config.CHAT_HISTORY_MAX_MESSAGES or sum(
            len(item.content.encode("utf-8")) for item in self.history
        ) > Config.CHAT_HISTORY_MAX_BYTES:
            self.history = self.history[2:]
        return self


class QueryResponse(BaseModel):
    query: str
    answer: str
