"""Resource template functionality."""

from __future__ import annotations

import inspect
import re
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field, TypeAdapter, validate_call

from mcp.server.fastmcp.resources.types import FunctionResource, Resource


class ResourceTemplate(BaseModel):
    """A template for dynamically creating resources."""

    uri_template: str = Field(
        description="URI template with parameters (e.g. weather://{city}/current)"
    )
    name: str = Field(description="Name of the resource")
    description: str | None = Field(description="Description of what the resource does")
    mime_type: str = Field(
        default="text/plain", description="MIME type of the resource content"
    )
    fn: Callable[..., Any] = Field(exclude=True)
    parameters: dict[str, Any] = Field(
        description="JSON schema for function parameters"
    )

    @classmethod
    def from_function(
        cls,
        fn: Callable[..., Any],
        uri_template: str,
        name: str | None = None,
        description: str | None = None,
        mime_type: str | None = None,
    ) -> ResourceTemplate:
        """Create a template from a function."""
        func_name = name or fn.__name__
        if func_name == "<lambda>":
            raise ValueError("You must provide a name for lambda functions")

        # Get schema from TypeAdapter - will fail if function isn't properly typed
        parameters = TypeAdapter(fn).json_schema()

        # ensure the arguments are properly cast
        fn = validate_call(fn)

        return cls(
            uri_template=uri_template,
            name=func_name,
            description=description or fn.__doc__ or "",
            mime_type=mime_type or "text/plain",
            fn=fn,
            parameters=parameters,
        )

    def matches(self, uri: str) -> dict[str, Any] | None:
        """Check if URI matches template and extract parameters."""
        # Use precompiled regex pattern for much faster matching.
        match = self._compiled_uri_re.match(uri)
        if match:
            return match.groupdict()
        return None

    async def create_resource(self, uri: str, params: dict[str, Any]) -> Resource:
        """Create a resource from the template with the given parameters."""
        try:
            # Call function and check if result is a coroutine
            result = self.fn(**params)
            if inspect.iscoroutine(result):
                result = await result

            return FunctionResource(
                uri=uri,  # type: ignore
                name=self.name,
                description=self.description,
                mime_type=self.mime_type,
                fn=lambda: result,  # Capture result in closure
            )
        except Exception as e:
            raise ValueError(f"Error creating resource from template: {e}")

    def __init__(self, **data: Any):
        super().__init__(**data)
        # Precompile the regex pattern only once per instance.
        self._compiled_uri_re = self._build_uri_regex(self.uri_template)

    @staticmethod
    def _build_uri_regex(uri_template: str) -> re.Pattern:
        # Replace {param} with named groups in regex.
        pattern = re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", uri_template)
        return re.compile(f"^{pattern}$")
