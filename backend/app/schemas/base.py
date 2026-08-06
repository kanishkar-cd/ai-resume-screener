from pydantic import BaseModel, ConfigDict


class APIModel(BaseModel):
    """Base DTO configured for validation from ORM attributes."""

    model_config = ConfigDict(from_attributes=True)
