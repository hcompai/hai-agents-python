from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote
from uuid import UUID

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.feedback import Feedback
from ...models.http_validation_error import HTTPValidationError
from ...types import UNSET, Response


def _get_kwargs(
    id: UUID,
    event_index: int,
    *,
    body: Feedback,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "put",
        "url": "/api/v2/sessions/{id}/events/{event_index}/feedback".format(
            id=quote(str(id), safe=""),
            event_index=quote(str(event_index), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Any | HTTPValidationError | None:
    if response.status_code == 204:
        response_204 = cast(Any, None)
        return response_204

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())

        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[Any | HTTPValidationError]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    id: UUID,
    event_index: int,
    *,
    client: AuthenticatedClient,
    body: Feedback,
) -> Response[Any | HTTPValidationError]:
    """Submit Event Feedback

     Record feedback on a single event in the session's history.

    Args:
        id (UUID):
        event_index (int):
        body (Feedback): Feedback on the semantic success of the trajectory.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        id=id,
        event_index=event_index,
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    id: UUID,
    event_index: int,
    *,
    client: AuthenticatedClient,
    body: Feedback,
) -> Any | HTTPValidationError | None:
    """Submit Event Feedback

     Record feedback on a single event in the session's history.

    Args:
        id (UUID):
        event_index (int):
        body (Feedback): Feedback on the semantic success of the trajectory.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError
    """

    return sync_detailed(
        id=id,
        event_index=event_index,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    id: UUID,
    event_index: int,
    *,
    client: AuthenticatedClient,
    body: Feedback,
) -> Response[Any | HTTPValidationError]:
    """Submit Event Feedback

     Record feedback on a single event in the session's history.

    Args:
        id (UUID):
        event_index (int):
        body (Feedback): Feedback on the semantic success of the trajectory.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        id=id,
        event_index=event_index,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    id: UUID,
    event_index: int,
    *,
    client: AuthenticatedClient,
    body: Feedback,
) -> Any | HTTPValidationError | None:
    """Submit Event Feedback

     Record feedback on a single event in the session's history.

    Args:
        id (UUID):
        event_index (int):
        body (Feedback): Feedback on the semantic success of the trajectory.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            id=id,
            event_index=event_index,
            client=client,
            body=body,
        )
    ).parsed
