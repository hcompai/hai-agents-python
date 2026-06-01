from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote
from uuid import UUID

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.trajectory_changes import TrajectoryChanges
from ...types import UNSET, Response, Unset


def _get_kwargs(
    id: UUID,
    *,
    from_index: int | Unset = 0,
    limit: int | None | Unset = UNSET,
    include_events: bool | Unset = True,
    wait_for_seconds: int | Unset = 0,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    params["from_index"] = from_index

    json_limit: int | None | Unset
    if isinstance(limit, Unset):
        json_limit = UNSET
    else:
        json_limit = limit
    params["limit"] = json_limit

    params["include_events"] = include_events

    params["wait_for_seconds"] = wait_for_seconds

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/api/v2/sessions/{id}/changes".format(
            id=quote(str(id), safe=""),
        ),
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Any | HTTPValidationError | TrajectoryChanges | None:
    if response.status_code == 200:
        response_200 = TrajectoryChanges.from_dict(response.json())

        return response_200

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
) -> Response[Any | HTTPValidationError | TrajectoryChanges]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    id: UUID,
    *,
    client: AuthenticatedClient,
    from_index: int | Unset = 0,
    limit: int | None | Unset = UNSET,
    include_events: bool | Unset = True,
    wait_for_seconds: int | Unset = 0,
) -> Response[Any | HTTPValidationError | TrajectoryChanges]:
    """Get Session Changes

     Long-poll for new events since ``from_index``; 204 if none arrive within ``wait_for_seconds``.

    Args:
        id (UUID):
        from_index (int | Unset):  Default: 0.
        limit (int | None | Unset):
        include_events (bool | Unset):  Default: True.
        wait_for_seconds (int | Unset):  Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError | TrajectoryChanges]
    """

    kwargs = _get_kwargs(
        id=id,
        from_index=from_index,
        limit=limit,
        include_events=include_events,
        wait_for_seconds=wait_for_seconds,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    id: UUID,
    *,
    client: AuthenticatedClient,
    from_index: int | Unset = 0,
    limit: int | None | Unset = UNSET,
    include_events: bool | Unset = True,
    wait_for_seconds: int | Unset = 0,
) -> Any | HTTPValidationError | TrajectoryChanges | None:
    """Get Session Changes

     Long-poll for new events since ``from_index``; 204 if none arrive within ``wait_for_seconds``.

    Args:
        id (UUID):
        from_index (int | Unset):  Default: 0.
        limit (int | None | Unset):
        include_events (bool | Unset):  Default: True.
        wait_for_seconds (int | Unset):  Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError | TrajectoryChanges
    """

    return sync_detailed(
        id=id,
        client=client,
        from_index=from_index,
        limit=limit,
        include_events=include_events,
        wait_for_seconds=wait_for_seconds,
    ).parsed


async def asyncio_detailed(
    id: UUID,
    *,
    client: AuthenticatedClient,
    from_index: int | Unset = 0,
    limit: int | None | Unset = UNSET,
    include_events: bool | Unset = True,
    wait_for_seconds: int | Unset = 0,
) -> Response[Any | HTTPValidationError | TrajectoryChanges]:
    """Get Session Changes

     Long-poll for new events since ``from_index``; 204 if none arrive within ``wait_for_seconds``.

    Args:
        id (UUID):
        from_index (int | Unset):  Default: 0.
        limit (int | None | Unset):
        include_events (bool | Unset):  Default: True.
        wait_for_seconds (int | Unset):  Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError | TrajectoryChanges]
    """

    kwargs = _get_kwargs(
        id=id,
        from_index=from_index,
        limit=limit,
        include_events=include_events,
        wait_for_seconds=wait_for_seconds,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    id: UUID,
    *,
    client: AuthenticatedClient,
    from_index: int | Unset = 0,
    limit: int | None | Unset = UNSET,
    include_events: bool | Unset = True,
    wait_for_seconds: int | Unset = 0,
) -> Any | HTTPValidationError | TrajectoryChanges | None:
    """Get Session Changes

     Long-poll for new events since ``from_index``; 204 if none arrive within ``wait_for_seconds``.

    Args:
        id (UUID):
        from_index (int | Unset):  Default: 0.
        limit (int | None | Unset):
        include_events (bool | Unset):  Default: True.
        wait_for_seconds (int | Unset):  Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError | TrajectoryChanges
    """

    return (
        await asyncio_detailed(
            id=id,
            client=client,
            from_index=from_index,
            limit=limit,
            include_events=include_events,
            wait_for_seconds=wait_for_seconds,
        )
    ).parsed
