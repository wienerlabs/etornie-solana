from pydantic import BaseModel, Field


class EtornieGPTRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    language: str = Field(default="tr", max_length=10)


class EtornieGPTResponse(BaseModel):
    answer: str
    country_detected: str | None = None
    model: str
