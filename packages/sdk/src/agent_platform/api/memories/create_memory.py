from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.create_memory import CreateMemory
from ...models.http_validation_error import HTTPValidationError
from ...models.memory_record import MemoryRecord
from ...types import UNSET, Response


def _get_kwargs(
    *,
    body: CreateMemory,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/v2/memories",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Any | HTTPValidationError | MemoryRecord | None:
    if response.status_code == 200:
        response_200 = MemoryRecord.from_dict(response.json())

        return response_200

    if response.status_code == 201:
        response_201 = cast(Any, None)
        return response_201

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())

        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[Any | HTTPValidationError | MemoryRecord]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: CreateMemory,
) -> Response[Any | HTTPValidationError | MemoryRecord]:
    """Create Memory

     Upsert a memory by ``(org_id, namespace, key)``. 201 on create, 200 on update.

    Args:
        body (CreateMemory): Upsert a memory by ``(org_id, namespace, key)``.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError | MemoryRecord]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
    body: CreateMemory,
) -> Any | HTTPValidationError | MemoryRecord | None:
    """Create Memory

     Upsert a memory by ``(org_id, namespace, key)``. 201 on create, 200 on update.

    Args:
        body (CreateMemory): Upsert a memory by ``(org_id, namespace, key)``.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError | MemoryRecord
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: CreateMemory,
) -> Response[Any | HTTPValidationError | MemoryRecord]:
    """Create Memory

     Upsert a memory by ``(org_id, namespace, key)``. 201 on create, 200 on update.

    Args:
        body (CreateMemory): Upsert a memory by ``(org_id, namespace, key)``.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError | MemoryRecord]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: CreateMemory,
) -> Any | HTTPValidationError | MemoryRecord | None:
    """Create Memory

     Upsert a memory by ``(org_id, namespace, key)``. 201 on create, 200 on update.

    Args:
        body (CreateMemory): Upsert a memory by ``(org_id, namespace, key)``.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError | MemoryRecord
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed
