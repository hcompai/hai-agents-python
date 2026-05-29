from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.list_memories_sort_type_0_item import ListMemoriesSortType0Item
from ...models.page_memory_record import PageMemoryRecord
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    namespace: None | str | Unset = UNSET,
    key: None | str | Unset = UNSET,
    page: int | Unset = 1,
    size: int | Unset = 10,
    sort: list[ListMemoriesSortType0Item] | None | Unset = UNSET,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_namespace: None | str | Unset
    if isinstance(namespace, Unset):
        json_namespace = UNSET
    else:
        json_namespace = namespace
    params["namespace"] = json_namespace

    json_key: None | str | Unset
    if isinstance(key, Unset):
        json_key = UNSET
    else:
        json_key = key
    params["key"] = json_key

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
        "url": "/api/v2/memories",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | PageMemoryRecord | None:
    if response.status_code == 200:
        response_200 = PageMemoryRecord.from_dict(response.json())

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
) -> Response[HTTPValidationError | PageMemoryRecord]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    namespace: None | str | Unset = UNSET,
    key: None | str | Unset = UNSET,
    page: int | Unset = 1,
    size: int | Unset = 10,
    sort: list[ListMemoriesSortType0Item] | None | Unset = UNSET,
) -> Response[HTTPValidationError | PageMemoryRecord]:
    """List Memories

     List org memories; optional exact-namespace and key-prefix filters.

    Args:
        namespace (None | str | Unset): Exact namespace filter.
        key (None | str | Unset): Key prefix filter.
        page (int | Unset): Page number (1-based) Default: 1.
        size (int | Unset): Number of items per page Default: 10.
        sort (list[ListMemoriesSortType0Item] | None | Unset): Sort by field

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | PageMemoryRecord]
    """

    kwargs = _get_kwargs(
        namespace=namespace,
        key=key,
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
    namespace: None | str | Unset = UNSET,
    key: None | str | Unset = UNSET,
    page: int | Unset = 1,
    size: int | Unset = 10,
    sort: list[ListMemoriesSortType0Item] | None | Unset = UNSET,
) -> HTTPValidationError | PageMemoryRecord | None:
    """List Memories

     List org memories; optional exact-namespace and key-prefix filters.

    Args:
        namespace (None | str | Unset): Exact namespace filter.
        key (None | str | Unset): Key prefix filter.
        page (int | Unset): Page number (1-based) Default: 1.
        size (int | Unset): Number of items per page Default: 10.
        sort (list[ListMemoriesSortType0Item] | None | Unset): Sort by field

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | PageMemoryRecord
    """

    return sync_detailed(
        client=client,
        namespace=namespace,
        key=key,
        page=page,
        size=size,
        sort=sort,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    namespace: None | str | Unset = UNSET,
    key: None | str | Unset = UNSET,
    page: int | Unset = 1,
    size: int | Unset = 10,
    sort: list[ListMemoriesSortType0Item] | None | Unset = UNSET,
) -> Response[HTTPValidationError | PageMemoryRecord]:
    """List Memories

     List org memories; optional exact-namespace and key-prefix filters.

    Args:
        namespace (None | str | Unset): Exact namespace filter.
        key (None | str | Unset): Key prefix filter.
        page (int | Unset): Page number (1-based) Default: 1.
        size (int | Unset): Number of items per page Default: 10.
        sort (list[ListMemoriesSortType0Item] | None | Unset): Sort by field

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | PageMemoryRecord]
    """

    kwargs = _get_kwargs(
        namespace=namespace,
        key=key,
        page=page,
        size=size,
        sort=sort,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    namespace: None | str | Unset = UNSET,
    key: None | str | Unset = UNSET,
    page: int | Unset = 1,
    size: int | Unset = 10,
    sort: list[ListMemoriesSortType0Item] | None | Unset = UNSET,
) -> HTTPValidationError | PageMemoryRecord | None:
    """List Memories

     List org memories; optional exact-namespace and key-prefix filters.

    Args:
        namespace (None | str | Unset): Exact namespace filter.
        key (None | str | Unset): Key prefix filter.
        page (int | Unset): Page number (1-based) Default: 1.
        size (int | Unset): Number of items per page Default: 10.
        sort (list[ListMemoriesSortType0Item] | None | Unset): Sort by field

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | PageMemoryRecord
    """

    return (
        await asyncio_detailed(
            client=client,
            namespace=namespace,
            key=key,
            page=page,
            size=size,
            sort=sort,
        )
    ).parsed
