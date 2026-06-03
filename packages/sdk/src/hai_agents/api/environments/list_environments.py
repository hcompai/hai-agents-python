from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.environment_kind import EnvironmentKind
from ...models.environment_page import EnvironmentPage
from ...models.http_validation_error import HTTPValidationError
from ...models.list_environments_sort_type_0_item import ListEnvironmentsSortType0Item
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    id: None | str | Unset = UNSET,
    kind: EnvironmentKind | None | Unset = UNSET,
    search: None | str | Unset = UNSET,
    page: int | Unset = 1,
    size: int | Unset = 10,
    sort: list[ListEnvironmentsSortType0Item] | None | Unset = UNSET,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_id: None | str | Unset
    if isinstance(id, Unset):
        json_id = UNSET
    else:
        json_id = id
    params["id"] = json_id

    json_kind: None | str | Unset
    if isinstance(kind, Unset):
        json_kind = UNSET
    elif isinstance(kind, EnvironmentKind):
        json_kind = kind.value
    else:
        json_kind = kind
    params["kind"] = json_kind

    json_search: None | str | Unset
    if isinstance(search, Unset):
        json_search = UNSET
    else:
        json_search = search
    params["search"] = json_search

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
        "url": "/api/v2/environments",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> EnvironmentPage | HTTPValidationError | None:
    if response.status_code == 200:
        response_200 = EnvironmentPage.from_dict(response.json())

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
) -> Response[EnvironmentPage | HTTPValidationError]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    id: None | str | Unset = UNSET,
    kind: EnvironmentKind | None | Unset = UNSET,
    search: None | str | Unset = UNSET,
    page: int | Unset = 1,
    size: int | Unset = 10,
    sort: list[ListEnvironmentsSortType0Item] | None | Unset = UNSET,
) -> Response[EnvironmentPage | HTTPValidationError]:
    """List Environments

     List reserved + caller's org environments.

    Args:
        id (None | str | Unset): Case-insensitive substring match on environment id.
        kind (EnvironmentKind | None | Unset): Filter by environment kind.
        search (None | str | Unset): Case-insensitive match on environment id or description.
        page (int | Unset): Page number (1-based) Default: 1.
        size (int | Unset): Number of items per page Default: 10.
        sort (list[ListEnvironmentsSortType0Item] | None | Unset): Sort by field

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvironmentPage | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        id=id,
        kind=kind,
        search=search,
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
    id: None | str | Unset = UNSET,
    kind: EnvironmentKind | None | Unset = UNSET,
    search: None | str | Unset = UNSET,
    page: int | Unset = 1,
    size: int | Unset = 10,
    sort: list[ListEnvironmentsSortType0Item] | None | Unset = UNSET,
) -> EnvironmentPage | HTTPValidationError | None:
    """List Environments

     List reserved + caller's org environments.

    Args:
        id (None | str | Unset): Case-insensitive substring match on environment id.
        kind (EnvironmentKind | None | Unset): Filter by environment kind.
        search (None | str | Unset): Case-insensitive match on environment id or description.
        page (int | Unset): Page number (1-based) Default: 1.
        size (int | Unset): Number of items per page Default: 10.
        sort (list[ListEnvironmentsSortType0Item] | None | Unset): Sort by field

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvironmentPage | HTTPValidationError
    """

    return sync_detailed(
        client=client,
        id=id,
        kind=kind,
        search=search,
        page=page,
        size=size,
        sort=sort,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    id: None | str | Unset = UNSET,
    kind: EnvironmentKind | None | Unset = UNSET,
    search: None | str | Unset = UNSET,
    page: int | Unset = 1,
    size: int | Unset = 10,
    sort: list[ListEnvironmentsSortType0Item] | None | Unset = UNSET,
) -> Response[EnvironmentPage | HTTPValidationError]:
    """List Environments

     List reserved + caller's org environments.

    Args:
        id (None | str | Unset): Case-insensitive substring match on environment id.
        kind (EnvironmentKind | None | Unset): Filter by environment kind.
        search (None | str | Unset): Case-insensitive match on environment id or description.
        page (int | Unset): Page number (1-based) Default: 1.
        size (int | Unset): Number of items per page Default: 10.
        sort (list[ListEnvironmentsSortType0Item] | None | Unset): Sort by field

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvironmentPage | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        id=id,
        kind=kind,
        search=search,
        page=page,
        size=size,
        sort=sort,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    id: None | str | Unset = UNSET,
    kind: EnvironmentKind | None | Unset = UNSET,
    search: None | str | Unset = UNSET,
    page: int | Unset = 1,
    size: int | Unset = 10,
    sort: list[ListEnvironmentsSortType0Item] | None | Unset = UNSET,
) -> EnvironmentPage | HTTPValidationError | None:
    """List Environments

     List reserved + caller's org environments.

    Args:
        id (None | str | Unset): Case-insensitive substring match on environment id.
        kind (EnvironmentKind | None | Unset): Filter by environment kind.
        search (None | str | Unset): Case-insensitive match on environment id or description.
        page (int | Unset): Page number (1-based) Default: 1.
        size (int | Unset): Number of items per page Default: 10.
        sort (list[ListEnvironmentsSortType0Item] | None | Unset): Sort by field

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvironmentPage | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            client=client,
            id=id,
            kind=kind,
            search=search,
            page=page,
            size=size,
            sort=sort,
        )
    ).parsed
