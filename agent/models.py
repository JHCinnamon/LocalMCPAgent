from pydantic import BaseModel

class Plan(BaseModel):
    goal: str
    requires_tools: bool
    steps: list[str]