"""Environments clients that accept flat keyword arguments as well as ``request=``.

Fern renders the ``POST /environments`` and ``PUT /environments/{id}`` bodies as unions
discriminated on ``kind`` (``web`` | ``desktop``), and it cannot inline a union into keyword
arguments — so the generated clients expose a single ``request=`` parameter. Adding the
``desktop`` kind therefore regressed the call style the docs and every caller written against
``<=1.0.5`` use::

    client.environments.create_environment(id="wide-browser", start_url="https://x.test")

These subclasses restore it. Flat fields are collected into the union member for the requested
``kind`` (``web`` when omitted), and an explicit ``request=`` model is forwarded untouched, so
both styles work. Unknown or kind-mismatched field names raise ``TypeError`` here instead of
riding along as pydantic extras — the union members are declared ``extra="allow"``, so a typo
would otherwise reach the server and come back as an opaque 422.
"""

from __future__ import annotations

import typing

import typing_extensions

from .core.request_options import RequestOptions
from .environments.client import AsyncEnvironmentsClient, EnvironmentsClient
from .environments.types.create_environment_request import (
    CreateEnvironmentRequest,
    CreateEnvironmentRequest_Desktop,
    CreateEnvironmentRequest_Web,
)
from .environments.types.update_environment_request_body import (
    UpdateEnvironmentRequestBody,
    UpdateEnvironmentRequestBody_Desktop,
    UpdateEnvironmentRequestBody_Web,
)
from .types.browser_host import BrowserHost
from .types.browser_mode import BrowserMode
from .types.browser_network import BrowserNetwork
from .types.desktop_host import DesktopHost
from .types.environment import Environment

__all__ = [
    "AsyncFlatEnvironmentsClient",
    "EnvironmentSpecParams",
    "FlatEnvironmentsClient",
]


class EnvironmentSpecParams(typing_extensions.TypedDict, total=False):
    """Flat environment-spec kwargs; mirror new union member fields here to keep autocomplete.

    A superset of the ``web`` and ``desktop`` members — which fields are actually legal depends
    on ``kind``, and is enforced at call time against the selected member's model fields.
    """

    id: typing_extensions.Required[str]
    kind: typing.Literal["web", "desktop"]
    host: typing.Union[BrowserHost, DesktopHost]
    start_url: typing.Optional[str]
    headless: typing.Optional[bool]
    session_id: typing.Optional[str]
    mode: typing.Optional[BrowserMode]
    vault_id: typing.Optional[str]
    browser_profile_id: typing.Optional[str]
    use_default_browser_profile: typing.Optional[bool]
    persist_browser_profile: typing.Optional[bool]
    network: typing.Optional[BrowserNetwork]


_CREATE_MEMBERS: typing.Mapping[str, typing.Any] = {
    "web": CreateEnvironmentRequest_Web,
    "desktop": CreateEnvironmentRequest_Desktop,
}
_UPDATE_MEMBERS: typing.Mapping[str, typing.Any] = {
    "web": UpdateEnvironmentRequestBody_Web,
    "desktop": UpdateEnvironmentRequestBody_Desktop,
}


def _build_spec(
    members: typing.Mapping[str, typing.Any],
    fields: typing.Dict[str, typing.Any],
    *,
    method: str,
    default_id: typing.Optional[str] = None,
) -> typing.Any:
    """Collect flat ``fields`` into the union member matching their ``kind``."""
    fields = dict(fields)
    if default_id is not None:
        fields.setdefault("id", default_id)
    kind = fields.pop("kind", None) or "web"
    if kind not in members:
        raise TypeError(
            f"{method}() cannot build a request body for kind={kind!r}; known kinds are "
            f"{', '.join(sorted(members))}. Pass request=<model> to send a kind this SDK "
            "version does not model yet."
        )
    model_cls = members[kind]
    allowed = set(model_cls.model_fields) - {"kind"}
    unexpected = sorted(set(fields) - allowed)
    if unexpected:
        raise TypeError(
            f"{method}() got unexpected keyword argument(s) {', '.join(unexpected)} for a "
            f"{kind!r} environment; valid fields are {', '.join(sorted(allowed))}."
        )
    if "id" not in fields:
        raise TypeError(f"{method}() missing required keyword argument: 'id'")
    return model_cls(**fields)


def _resolve_request(
    request: typing.Optional[typing.Any],
    fields: typing.Dict[str, typing.Any],
    members: typing.Mapping[str, typing.Any],
    *,
    method: str,
    default_id: typing.Optional[str] = None,
) -> typing.Any:
    if request is None:
        return _build_spec(members, fields, method=method, default_id=default_id)
    if fields:
        raise TypeError(
            f"{method}() takes either request= or flat environment fields, not both; got "
            f"request= together with {', '.join(sorted(fields))}."
        )
    return request


def _path_id(
    positional: typing.Optional[str],
    request: typing.Optional[typing.Any],
    fields: typing.Mapping[str, typing.Any],
    *,
    method: str,
) -> str:
    """Resolve the ``{id}`` path segment from the positional arg, the flat fields, or ``request``."""
    for candidate in (positional, fields.get("id"), getattr(request, "id", None)):
        if candidate is not None:
            return candidate
    raise TypeError(f"{method}() missing the environment id; pass it positionally or as id=.")


class FlatEnvironmentsClient(EnvironmentsClient):
    def create_environment(
        self,
        *,
        request: typing.Optional[CreateEnvironmentRequest] = None,
        request_options: typing.Optional[RequestOptions] = None,
        **fields: typing_extensions.Unpack[EnvironmentSpecParams],
    ) -> Environment:
        """Create an environment from flat fields, or from a prebuilt ``request`` model.

        Parameters
        ----------
        request : typing.Optional[CreateEnvironmentRequest]
            A prebuilt union member. Mutually exclusive with the flat fields below.

        request_options : typing.Optional[RequestOptions]
            Request-specific configuration.

        **fields : typing_extensions.Unpack[EnvironmentSpecParams]
            Environment spec fields, collected into the member for ``kind`` (``web`` by default).

        Returns
        -------
        Environment
            Successful Response

        Examples
        --------
        from hai_agents import Client

        client = Client(
            api_key="YOUR_API_KEY",
        )
        client.environments.create_environment(
            id="wide-browser",
            mode={"type": "visual", "width": 1920, "height": 1080},
        )
        """
        return super().create_environment(
            request=_resolve_request(request, fields, _CREATE_MEMBERS, method="create_environment"),
            request_options=request_options,
        )

    def update_environment(
        self,
        id: typing.Optional[str] = None,
        /,
        *,
        request: typing.Optional[UpdateEnvironmentRequestBody] = None,
        request_options: typing.Optional[RequestOptions] = None,
        **fields: typing_extensions.Unpack[EnvironmentSpecParams],
    ) -> Environment:
        """Replace an environment spec from flat fields, or from a prebuilt ``request`` model.

        Parameters
        ----------
        id : typing.Optional[str]
            Environment to replace. Defaults to the ``id`` field of the new spec, so it only
            needs passing when the two differ.

        request : typing.Optional[UpdateEnvironmentRequestBody]
            A prebuilt union member. Mutually exclusive with the flat fields below.

        request_options : typing.Optional[RequestOptions]
            Request-specific configuration.

        **fields : typing_extensions.Unpack[EnvironmentSpecParams]
            Environment spec fields, collected into the member for ``kind`` (``web`` by default).

        Returns
        -------
        Environment
            Successful Response

        Examples
        --------
        from hai_agents import Client

        client = Client(
            api_key="YOUR_API_KEY",
        )
        client.environments.update_environment(
            id="wide-browser",
            start_url="https://example.com",
        )
        """
        environment_id = _path_id(id, request, fields, method="update_environment")
        if request is not None:
            fields.pop("id", None)  # it only carried the path segment
        return super().update_environment(
            environment_id,
            request=_resolve_request(
                request, fields, _UPDATE_MEMBERS, method="update_environment", default_id=environment_id
            ),
            request_options=request_options,
        )


class AsyncFlatEnvironmentsClient(AsyncEnvironmentsClient):
    async def create_environment(
        self,
        *,
        request: typing.Optional[CreateEnvironmentRequest] = None,
        request_options: typing.Optional[RequestOptions] = None,
        **fields: typing_extensions.Unpack[EnvironmentSpecParams],
    ) -> Environment:
        """Create an environment from flat fields, or from a prebuilt ``request`` model.

        Parameters
        ----------
        request : typing.Optional[CreateEnvironmentRequest]
            A prebuilt union member. Mutually exclusive with the flat fields below.

        request_options : typing.Optional[RequestOptions]
            Request-specific configuration.

        **fields : typing_extensions.Unpack[EnvironmentSpecParams]
            Environment spec fields, collected into the member for ``kind`` (``web`` by default).

        Returns
        -------
        Environment
            Successful Response

        Examples
        --------
        import asyncio

        from hai_agents import AsyncClient

        client = AsyncClient(
            api_key="YOUR_API_KEY",
        )


        async def main() -> None:
            await client.environments.create_environment(
                id="wide-browser",
                mode={"type": "visual", "width": 1920, "height": 1080},
            )


        asyncio.run(main())
        """
        return await super().create_environment(
            request=_resolve_request(request, fields, _CREATE_MEMBERS, method="create_environment"),
            request_options=request_options,
        )

    async def update_environment(
        self,
        id: typing.Optional[str] = None,
        /,
        *,
        request: typing.Optional[UpdateEnvironmentRequestBody] = None,
        request_options: typing.Optional[RequestOptions] = None,
        **fields: typing_extensions.Unpack[EnvironmentSpecParams],
    ) -> Environment:
        """Replace an environment spec from flat fields, or from a prebuilt ``request`` model.

        Parameters
        ----------
        id : typing.Optional[str]
            Environment to replace. Defaults to the ``id`` field of the new spec, so it only
            needs passing when the two differ.

        request : typing.Optional[UpdateEnvironmentRequestBody]
            A prebuilt union member. Mutually exclusive with the flat fields below.

        request_options : typing.Optional[RequestOptions]
            Request-specific configuration.

        **fields : typing_extensions.Unpack[EnvironmentSpecParams]
            Environment spec fields, collected into the member for ``kind`` (``web`` by default).

        Returns
        -------
        Environment
            Successful Response

        Examples
        --------
        import asyncio

        from hai_agents import AsyncClient

        client = AsyncClient(
            api_key="YOUR_API_KEY",
        )


        async def main() -> None:
            await client.environments.update_environment(
                id="wide-browser",
                start_url="https://example.com",
            )


        asyncio.run(main())
        """
        environment_id = _path_id(id, request, fields, method="update_environment")
        if request is not None:
            fields.pop("id", None)  # it only carried the path segment
        return await super().update_environment(
            environment_id,
            request=_resolve_request(
                request, fields, _UPDATE_MEMBERS, method="update_environment", default_id=environment_id
            ),
            request_options=request_options,
        )
