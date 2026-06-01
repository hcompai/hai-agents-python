from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.agent_record import AgentRecord
from ...models.http_validation_error import HTTPValidationError
from ...models.update_agent import UpdateAgent
from ...types import UNSET, Response


def _get_kwargs(
    agent_identifier: str,
    *,
    body: UpdateAgent,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "put",
        "url": "/api/v2/agents/{agent_identifier}".format(
            agent_identifier=quote(str(agent_identifier), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
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
    body: UpdateAgent,
) -> Response[AgentRecord | HTTPValidationError]:
    """Update Agent

     Replace ``spec``. ``spec.name`` must match the URL identifier; renames are not supported.

    Args:
        agent_identifier (str):
        body (UpdateAgent): ``PUT /api/v2/agents/{agent_identifier}`` body. Full replace;
            ``spec.name`` is immutable.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[AgentRecord | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        agent_identifier=agent_identifier,
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    agent_identifier: str,
    *,
    client: AuthenticatedClient,
    body: UpdateAgent,
) -> AgentRecord | HTTPValidationError | None:
    """Update Agent

     Replace ``spec``. ``spec.name`` must match the URL identifier; renames are not supported.

    Args:
        agent_identifier (str):
        body (UpdateAgent): ``PUT /api/v2/agents/{agent_identifier}`` body. Full replace;
            ``spec.name`` is immutable.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        AgentRecord | HTTPValidationError
    """

    return sync_detailed(
        agent_identifier=agent_identifier,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    agent_identifier: str,
    *,
    client: AuthenticatedClient,
    body: UpdateAgent,
) -> Response[AgentRecord | HTTPValidationError]:
    """Update Agent

     Replace ``spec``. ``spec.name`` must match the URL identifier; renames are not supported.

    Args:
        agent_identifier (str):
        body (UpdateAgent): ``PUT /api/v2/agents/{agent_identifier}`` body. Full replace;
            ``spec.name`` is immutable.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[AgentRecord | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        agent_identifier=agent_identifier,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    agent_identifier: str,
    *,
    client: AuthenticatedClient,
    body: UpdateAgent,
) -> AgentRecord | HTTPValidationError | None:
    """Update Agent

     Replace ``spec``. ``spec.name`` must match the URL identifier; renames are not supported.

    Args:
        agent_identifier (str):
        body (UpdateAgent): ``PUT /api/v2/agents/{agent_identifier}`` body. Full replace;
            ``spec.name`` is immutable.

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
            body=body,
        )
    ).parsed
