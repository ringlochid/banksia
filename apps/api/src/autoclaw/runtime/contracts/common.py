from typing import Annotated

from pydantic import StringConstraints

RuntimeSchemaText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

__all__ = ["RuntimeSchemaText"]
