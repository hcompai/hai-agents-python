from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.agent_record import AgentRecord
from ...models.http_validation_error import HTTPValidationError
from ...types import UNSET, Response


def _get_kwargs(
    agent_identifier: str,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/api/v2/agents/{agent_identifier}".format(
            agent_identifier=quote(str(agent_identifier), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> AgentRecord | HTTPValidationError | None:
    if response.status_code == 200:
        response_200 = AgentRecord.from_dict(response.json())

        return response_200

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())

        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[AgentRecord | HTTPValidationError]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    agent_identifier: str,
    *,
    client: AuthenticatedClient,
) -> Response[AgentRecord | HTTPValidationError]:
    """Get Agent

     Fetch by identifier; 404 if not visible. ``:path`` so slash-containing ids round-trip.

    Args:
        agent_identifier (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[AgentRecord | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        agent_identifier=agent_identifier,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    agent_identifier: str,
    *,
    client: AuthenticatedClient,
) -> AgentRecord | HTTPValidationError | None:
    """Get Agent

     Fetch by identifier; 404 if not visible. ``:path`` so slash-containing ids round-trip.

    Args:
        agent_identifier (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        AgentRecord | HTTPValidationError
    """

    return sync_detailed(
        agent_identifier=agent_identifier,
        client=client,
    ).parsed


async def asyncio_detailed(
    agent_identifier: str,
    *,
    client: AuthenticatedClient,
) -> Response[AgentRecord | HTTPValidationError]:
    """Get Agent

     Fetch by identifier; 404 if not visible. ``:path`` so slash-containing ids round-trip.

    Args:
        agent_identifier (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[AgentRecord | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        agent_identifier=agent_identifier,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    agent_identifier: str,
    *,
    client: AuthenticatedClient,
) -> AgentRecord | HTTPValidationError | None:
    """Get Agent

     Fetch by identifier; 404 if not visible. ``:path`` so slash-containing ids round-trip.

    Args:
        agent_identifier (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        AgentRecord | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            agent_identifier=agent_identifier,
            client=client,
        )
    ).parsed
