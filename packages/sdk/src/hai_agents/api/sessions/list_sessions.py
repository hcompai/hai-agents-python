from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.list_sessions_owner import ListSessionsOwner
from ...models.list_sessions_sort_type_0_item import ListSessionsSortType0Item
from ...models.page_session_summary import PageSessionSummary
from ...models.trajectory_status import TrajectoryStatus
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    owner: ListSessionsOwner | Unset = ListSessionsOwner.ME_IN_ORGANIZATION,
    status: list[TrajectoryStatus] | None | Unset = UNSET,
    agent: list[str] | None | Unset = UNSET,
    group_id: None | str | Unset = UNSET,
    parent_session_id: None | str | Unset = UNSET,
    page: int | Unset = 1,
    size: int | Unset = 10,
    sort: list[ListSessionsSortType0Item] | None | Unset = UNSET,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_owner: str | Unset = UNSET
    if not isinstance(owner, Unset):
        json_owner = owner.value

    params["owner"] = json_owner

    json_status: list[str] | None | Unset
    if isinstance(status, Unset):
        json_status = UNSET
    elif isinstance(status, list):
        json_status = []
        for status_type_0_item_data in status:
            status_type_0_item = status_type_0_item_data.value
            json_status.append(status_type_0_item)

    else:
        json_status = status
    params["status"] = json_status

    json_agent: list[str] | None | Unset
    if isinstance(agent, Unset):
        json_agent = UNSET
    elif isinstance(agent, list):
        json_agent = agent

    else:
        json_agent = agent
    params["agent"] = json_agent

    json_group_id: None | str | Unset
    if isinstance(group_id, Unset):
        json_group_id = UNSET
    else:
        json_group_id = group_id
    params["group_id"] = json_group_id

    json_parent_session_id: None | str | Unset
    if isinstance(parent_session_id, Unset):
        json_parent_session_id = UNSET
    else:
        json_parent_session_id = parent_session_id
    params["parent_session_id"] = json_parent_session_id

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

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/api/v2/sessions",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | PageSessionSummary | None:
    if response.status_code == 200:
        response_200 = PageSessionSummary.from_dict(response.json())

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
) -> Response[HTTPValidationError | PageSessionSummary]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    owner: ListSessionsOwner | Unset = ListSessionsOwner.ME_IN_ORGANIZATION,
    status: list[TrajectoryStatus] | None | Unset = UNSET,
    agent: list[str] | None | Unset = UNSET,
    group_id: None | str | Unset = UNSET,
    parent_session_id: None | str | Unset = UNSET,
    page: int | Unset = 1,
    size: int | Unset = 10,
    sort: list[ListSessionsSortType0Item] | None | Unset = UNSET,
) -> Response[HTTPValidationError | PageSessionSummary]:
    """List Sessions

     List sessions visible to ``user``.

    Args:
        owner (ListSessionsOwner | Unset):  Default: ListSessionsOwner.ME_IN_ORGANIZATION.
        status (list[TrajectoryStatus] | None | Unset):
        agent (list[str] | None | Unset):
        group_id (None | str | Unset):
        parent_session_id (None | str | Unset):
        page (int | Unset): Page number (1-based) Default: 1.
        size (int | Unset): Number of items per page Default: 10.
        sort (list[ListSessionsSortType0Item] | None | Unset): Sort by field

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | PageSessionSummary]
    """

    kwargs = _get_kwargs(
        owner=owner,
        status=status,
        agent=agent,
        group_id=group_id,
        parent_session_id=parent_session_id,
        page=page,
        size=size,
        sort=sort,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
    owner: ListSessionsOwner | Unset = ListSessionsOwner.ME_IN_ORGANIZATION,
    status: list[TrajectoryStatus] | None | Unset = UNSET,
    agent: list[str] | None | Unset = UNSET,
    group_id: None | str | Unset = UNSET,
    parent_session_id: None | str | Unset = UNSET,
    page: int | Unset = 1,
    size: int | Unset = 10,
    sort: list[ListSessionsSortType0Item] | None | Unset = UNSET,
) -> HTTPValidationError | PageSessionSummary | None:
    """List Sessions

     List sessions visible to ``user``.

    Args:
        owner (ListSessionsOwner | Unset):  Default: ListSessionsOwner.ME_IN_ORGANIZATION.
        status (list[TrajectoryStatus] | None | Unset):
        agent (list[str] | None | Unset):
        group_id (None | str | Unset):
        parent_session_id (None | str | Unset):
        page (int | Unset): Page number (1-based) Default: 1.
        size (int | Unset): Number of items per page Default: 10.
        sort (list[ListSessionsSortType0Item] | None | Unset): Sort by field

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | PageSessionSummary
    """

    return sync_detailed(
        client=client,
        owner=owner,
        status=status,
        agent=agent,
        group_id=group_id,
        parent_session_id=parent_session_id,
        page=page,
        size=size,
        sort=sort,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    owner: ListSessionsOwner | Unset = ListSessionsOwner.ME_IN_ORGANIZATION,
    status: list[TrajectoryStatus] | None | Unset = UNSET,
    agent: list[str] | None | Unset = UNSET,
    group_id: None | str | Unset = UNSET,
    parent_session_id: None | str | Unset = UNSET,
    page: int | Unset = 1,
    size: int | Unset = 10,
    sort: list[ListSessionsSortType0Item] | None | Unset = UNSET,
) -> Response[HTTPValidationError | PageSessionSummary]:
    """List Sessions

     List sessions visible to ``user``.

    Args:
        owner (ListSessionsOwner | Unset):  Default: ListSessionsOwner.ME_IN_ORGANIZATION.
        status (list[TrajectoryStatus] | None | Unset):
        agent (list[str] | None | Unset):
        group_id (None | str | Unset):
        parent_session_id (None | str | Unset):
        page (int | Unset): Page number (1-based) Default: 1.
        size (int | Unset): Number of items per page Default: 10.
        sort (list[ListSessionsSortType0Item] | None | Unset): Sort by field

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | PageSessionSummary]
    """

    kwargs = _get_kwargs(
        owner=owner,
        status=status,
        agent=agent,
        group_id=group_id,
        parent_session_id=parent_session_id,
        page=page,
        size=size,
        sort=sort,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    owner: ListSessionsOwner | Unset = ListSessionsOwner.ME_IN_ORGANIZATION,
    status: list[TrajectoryStatus] | None | Unset = UNSET,
    agent: list[str] | None | Unset = UNSET,
    group_id: None | str | Unset = UNSET,
    parent_session_id: None | str | Unset = UNSET,
    page: int | Unset = 1,
    size: int | Unset = 10,
    sort: list[ListSessionsSortType0Item] | None | Unset = UNSET,
) -> HTTPValidationError | PageSessionSummary | None:
    """List Sessions

     List sessions visible to ``user``.

    Args:
        owner (ListSessionsOwner | Unset):  Default: ListSessionsOwner.ME_IN_ORGANIZATION.
        status (list[TrajectoryStatus] | None | Unset):
        agent (list[str] | None | Unset):
        group_id (None | str | Unset):
        parent_session_id (None | str | Unset):
        page (int | Unset): Page number (1-based) Default: 1.
        size (int | Unset): Number of items per page Default: 10.
        sort (list[ListSessionsSortType0Item] | None | Unset): Sort by field

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | PageSessionSummary
    """

    return (
        await asyncio_detailed(
            client=client,
            owner=owner,
            status=status,
            agent=agent,
            group_id=group_id,
            parent_session_id=parent_session_id,
            page=page,
            size=size,
            sort=sort,
        )
    ).parsed
