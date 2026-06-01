from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote
from uuid import UUID

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.list_session_events_sort_type_0_item import ListSessionEventsSortType0Item
from ...models.page_trajectory_event import PageTrajectoryEvent
from ...types import UNSET, Response, Unset


def _get_kwargs(
    id: UUID,
    *,
    page: int | Unset = 1,
    size: int | Unset = 50,
    sort: list[ListSessionEventsSortType0Item] | None | Unset = UNSET,
    type_: None | str | Unset = UNSET,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    params["page"] = page

    params["size"] = size

    json_sort: list[str] | None | Unset
    if isinstance(sort, Unset):
        json_sort = UNSET
    elif isinstance(sort, list):
        json_sort = []
        for sort_type_0_item_data in sort:
            sort_type_0_item = sort_type_0_item_data.value
            json_sort.append(sort_type_0_item)

    else:
        json_sort = sort
    params["sort"] = json_sort

    json_type_: None | str | Unset
    if isinstance(type_, Unset):
        json_type_ = UNSET
    else:
        json_type_ = type_
    params["type"] = json_type_

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/api/v2/sessions/{id}/events".format(
            id=quote(str(id), safe=""),
        ),
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | PageTrajectoryEvent | None:
    if response.status_code == 200:
        response_200 = PageTrajectoryEvent.from_dict(response.json())

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
) -> Response[HTTPValidationError | PageTrajectoryEvent]:
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
    page: int | Unset = 1,
    size: int | Unset = 50,
    sort: list[ListSessionEventsSortType0Item] | None | Unset = UNSET,
    type_: None | str | Unset = UNSET,
) -> Response[HTTPValidationError | PageTrajectoryEvent]:
    """List Session Events

     Paginated event history. Use ``/changes`` for live tailing.

    Args:
        id (UUID):
        page (int | Unset):  Default: 1.
        size (int | Unset):  Default: 50.
        sort (list[ListSessionEventsSortType0Item] | None | Unset):
        type_ (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | PageTrajectoryEvent]
    """

    kwargs = _get_kwargs(
        id=id,
        page=page,
        size=size,
        sort=sort,
        type_=type_,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    id: UUID,
    *,
    client: AuthenticatedClient,
    page: int | Unset = 1,
    size: int | Unset = 50,
    sort: list[ListSessionEventsSortType0Item] | None | Unset = UNSET,
    type_: None | str | Unset = UNSET,
) -> HTTPValidationError | PageTrajectoryEvent | None:
    """List Session Events

     Paginated event history. Use ``/changes`` for live tailing.

    Args:
        id (UUID):
        page (int | Unset):  Default: 1.
        size (int | Unset):  Default: 50.
        sort (list[ListSessionEventsSortType0Item] | None | Unset):
        type_ (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | PageTrajectoryEvent
    """

    return sync_detailed(
        id=id,
        client=client,
        page=page,
        size=size,
        sort=sort,
        type_=type_,
    ).parsed


async def asyncio_detailed(
    id: UUID,
    *,
    client: AuthenticatedClient,
    page: int | Unset = 1,
    size: int | Unset = 50,
    sort: list[ListSessionEventsSortType0Item] | None | Unset = UNSET,
    type_: None | str | Unset = UNSET,
) -> Response[HTTPValidationError | PageTrajectoryEvent]:
    """List Session Events

     Paginated event history. Use ``/changes`` for live tailing.

    Args:
        id (UUID):
        page (int | Unset):  Default: 1.
        size (int | Unset):  Default: 50.
        sort (list[ListSessionEventsSortType0Item] | None | Unset):
        type_ (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | PageTrajectoryEvent]
    """

    kwargs = _get_kwargs(
        id=id,
        page=page,
        size=size,
        sort=sort,
        type_=type_,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    id: UUID,
    *,
    client: AuthenticatedClient,
    page: int | Unset = 1,
    size: int | Unset = 50,
    sort: list[ListSessionEventsSortType0Item] | None | Unset = UNSET,
    type_: None | str | Unset = UNSET,
) -> HTTPValidationError | PageTrajectoryEvent | None:
    """List Session Events

     Paginated event history. Use ``/changes`` for live tailing.

    Args:
        id (UUID):
        page (int | Unset):  Default: 1.
        size (int | Unset):  Default: 50.
        sort (list[ListSessionEventsSortType0Item] | None | Unset):
        type_ (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | PageTrajectoryEvent
    """

    return (
        await asyncio_detailed(
            id=id,
            client=client,
            page=page,
            size=size,
            sort=sort,
            type_=type_,
        )
    ).parsed
