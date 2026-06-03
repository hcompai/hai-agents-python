from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.list_skills_sort_type_0_item import ListSkillsSortType0Item
from ...models.page_skill import PageSkill
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    name: None | str | Unset = UNSET,
    search: None | str | Unset = UNSET,
    page: int | Unset = 1,
    size: int | Unset = 10,
    sort: list[ListSkillsSortType0Item] | None | Unset = UNSET,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_name: None | str | Unset
    if isinstance(name, Unset):
        json_name = UNSET
    else:
        json_name = name
    params["name"] = json_name

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
        "url": "/api/v2/skills",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | PageSkill | None:
    if response.status_code == 200:
        response_200 = PageSkill.from_dict(response.json())

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
) -> Response[HTTPValidationError | PageSkill]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    name: None | str | Unset = UNSET,
    search: None | str | Unset = UNSET,
    page: int | Unset = 1,
    size: int | Unset = 10,
    sort: list[ListSkillsSortType0Item] | None | Unset = UNSET,
) -> Response[HTTPValidationError | PageSkill]:
    """List Skills

     List reserved + caller's org skills, optionally filtered by name or text search.

    Args:
        name (None | str | Unset): Case-insensitive substring match on skill name.
        search (None | str | Unset): Case-insensitive match on skill name or description.
        page (int | Unset): Page number (1-based) Default: 1.
        size (int | Unset): Number of items per page Default: 10.
        sort (list[ListSkillsSortType0Item] | None | Unset): Sort by field

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | PageSkill]
    """

    kwargs = _get_kwargs(
        name=name,
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
    name: None | str | Unset = UNSET,
    search: None | str | Unset = UNSET,
    page: int | Unset = 1,
    size: int | Unset = 10,
    sort: list[ListSkillsSortType0Item] | None | Unset = UNSET,
) -> HTTPValidationError | PageSkill | None:
    """List Skills

     List reserved + caller's org skills, optionally filtered by name or text search.

    Args:
        name (None | str | Unset): Case-insensitive substring match on skill name.
        search (None | str | Unset): Case-insensitive match on skill name or description.
        page (int | Unset): Page number (1-based) Default: 1.
        size (int | Unset): Number of items per page Default: 10.
        sort (list[ListSkillsSortType0Item] | None | Unset): Sort by field

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | PageSkill
    """

    return sync_detailed(
        client=client,
        name=name,
        search=search,
        page=page,
        size=size,
        sort=sort,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    name: None | str | Unset = UNSET,
    search: None | str | Unset = UNSET,
    page: int | Unset = 1,
    size: int | Unset = 10,
    sort: list[ListSkillsSortType0Item] | None | Unset = UNSET,
) -> Response[HTTPValidationError | PageSkill]:
    """List Skills

     List reserved + caller's org skills, optionally filtered by name or text search.

    Args:
        name (None | str | Unset): Case-insensitive substring match on skill name.
        search (None | str | Unset): Case-insensitive match on skill name or description.
        page (int | Unset): Page number (1-based) Default: 1.
        size (int | Unset): Number of items per page Default: 10.
        sort (list[ListSkillsSortType0Item] | None | Unset): Sort by field

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | PageSkill]
    """

    kwargs = _get_kwargs(
        name=name,
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
    name: None | str | Unset = UNSET,
    search: None | str | Unset = UNSET,
    page: int | Unset = 1,
    size: int | Unset = 10,
    sort: list[ListSkillsSortType0Item] | None | Unset = UNSET,
) -> HTTPValidationError | PageSkill | None:
    """List Skills

     List reserved + caller's org skills, optionally filtered by name or text search.

    Args:
        name (None | str | Unset): Case-insensitive substring match on skill name.
        search (None | str | Unset): Case-insensitive match on skill name or description.
        page (int | Unset): Page number (1-based) Default: 1.
        size (int | Unset): Number of items per page Default: 10.
        sort (list[ListSkillsSortType0Item] | None | Unset): Sort by field

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | PageSkill
    """

    return (
        await asyncio_detailed(
            client=client,
            name=name,
            search=search,
            page=page,
            size=size,
            sort=sort,
        )
    ).parsed
