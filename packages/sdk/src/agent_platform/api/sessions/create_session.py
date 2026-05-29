from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.session import Session
from ...models.session_request import SessionRequest
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    body: SessionRequest,
    idempotency_key: None | str | Unset = UNSET,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}
    if not isinstance(idempotency_key, Unset):
        headers["Idempotency-Key"] = idempotency_key

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/v2/sessions",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | Session | None:
    if response.status_code == 201:
        response_201 = Session.from_dict(response.json())

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
) -> Response[HTTPValidationError | Session]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: SessionRequest,
    idempotency_key: None | str | Unset = UNSET,
) -> Response[HTTPValidationError | Session]:
    """Create Session

     Create an agentic session.

    Pass ``Idempotency-Key`` for safe retries: identical requests within 24h
    return the original session; reuse with a different body returns 422.

    Args:
        idempotency_key (None | str | Unset):
        body (SessionRequest): ``POST /api/v2/sessions`` body.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | Session]
    """

    kwargs = _get_kwargs(
        body=body,
        idempotency_key=idempotency_key,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
    body: SessionRequest,
    idempotency_key: None | str | Unset = UNSET,
) -> HTTPValidationError | Session | None:
    """Create Session

     Create an agentic session.

    Pass ``Idempotency-Key`` for safe retries: identical requests within 24h
    return the original session; reuse with a different body returns 422.

    Args:
        idempotency_key (None | str | Unset):
        body (SessionRequest): ``POST /api/v2/sessions`` body.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | Session
    """

    return sync_detailed(
        client=client,
        body=body,
        idempotency_key=idempotency_key,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: SessionRequest,
    idempotency_key: None | str | Unset = UNSET,
) -> Response[HTTPValidationError | Session]:
    """Create Session

     Create an agentic session.

    Pass ``Idempotency-Key`` for safe retries: identical requests within 24h
    return the original session; reuse with a different body returns 422.

    Args:
        idempotency_key (None | str | Unset):
        body (SessionRequest): ``POST /api/v2/sessions`` body.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | Session]
    """

    kwargs = _get_kwargs(
        body=body,
        idempotency_key=idempotency_key,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: SessionRequest,
    idempotency_key: None | str | Unset = UNSET,
) -> HTTPValidationError | Session | None:
    """Create Session

     Create an agentic session.

    Pass ``Idempotency-Key`` for safe retries: identical requests within 24h
    return the original session; reuse with a different body returns 422.

    Args:
        idempotency_key (None | str | Unset):
        body (SessionRequest): ``POST /api/v2/sessions`` body.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | Session
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
            idempotency_key=idempotency_key,
        )
    ).parsed
