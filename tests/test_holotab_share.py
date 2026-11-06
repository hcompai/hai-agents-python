from __future__ import annotations

import json
import sys
import threading
import time
from collections.abc import Callable, Iterator

import pytest

from hai_agents_local.holotab import link as link_module
from hai_agents_local.holotab.endpoint import STORE_EXTENSION_ID, Endpoint, TcpEndpoint, UnixEndpoint
from hai_agents_local.holotab.link import HoloTabLink

from .holotab_helpers import WAIT_S, hello, short_dir

MakeEndpoint = Callable[[object], Endpoint]


@pytest.fixture(params=["unix", "tcp"])
def make_endpoint(request: pytest.FixtureRequest) -> MakeEndpoint:
    if request.param == "unix":
        if sys.platform == "win32":
            pytest.skip("a Unix socket endpoint does not exist on Windows")
        return lambda folder: UnixEndpoint(folder / "l.sock")
    return lambda folder: TcpEndpoint(folder / "link.json")


@pytest.fixture
def folder() -> Iterator[object]:
    with short_dir() as path:
        yield path


def until(check: Callable[[], bool]) -> bool:
    deadline = time.monotonic() + WAIT_S
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.01)
    return False


def serve_in_thread(link: HoloTabLink, channel: str, answers: list) -> threading.Thread:
    worker = threading.Thread(
        target=lambda: answers.append(
            link.serve(channel, "http://127.0.0.1:9", "token", label=channel, client="Holo CLI")
        )
    )
    worker.start()
    return worker


def test_the_first_process_owns_the_endpoint_and_the_next_attaches(make_endpoint: MakeEndpoint, folder) -> None:
    owner, client = HoloTabLink(make_endpoint(folder)), HoloTabLink(make_endpoint(folder))
    try:
        owner.start()
        client.start()
        assert (owner.role, client.role) == ("owner", "client")
        assert until(lambda: len(owner._peers) == 1)
    finally:
        client.close()
        owner.close()


def test_a_client_learns_the_extension_is_connected_even_when_it_attached_late(
    make_endpoint: MakeEndpoint, folder
) -> None:
    owner, client = HoloTabLink(make_endpoint(folder)), HoloTabLink(make_endpoint(folder))
    try:
        owner.start()
        extension = hello(owner, "1.4.11")
        client.start()
        assert client.wait_connected(WAIT_S)
        assert client.extension == {"id": STORE_EXTENSION_ID, "version": "1.4.11"}
        extension.close()
        assert until(lambda: client.extension is None)
    finally:
        client.close()
        owner.close()


def test_a_client_asks_the_owner_to_serve_its_channel_and_hears_the_answer(make_endpoint: MakeEndpoint, folder) -> None:
    owner, client = HoloTabLink(make_endpoint(folder)), HoloTabLink(make_endpoint(folder))
    try:
        owner.start()
        extension = hello(owner)
        reader = extension.makefile("rb")
        client.start()
        assert client.wait_connected(WAIT_S)
        answers: list = []
        worker = serve_in_thread(client, "client-run", answers)
        asked = json.loads(reader.readline())
        assert (asked["type"], asked["channel"], asked["base_url"], asked["client"]) == (
            "SERVE_CHANNEL",
            "client-run",
            "http://127.0.0.1:9",
            "Holo CLI",
        )
        extension.sendall(json.dumps({"type": "SERVING", "channel": "client-run"}).encode() + b"\n")
        worker.join(WAIT_S)
        assert answers == [{"type": "SERVING", "channel": "client-run"}]

        client.relabel("client-run", "Renamed")
        assert json.loads(reader.readline()) == {"type": "LABEL_CHANNEL", "channel": "client-run", "title": "Renamed"}
        client.stop("client-run")
        assert json.loads(reader.readline())["type"] == "STOP_CHANNEL"
    finally:
        client.close()
        owner.close()


def test_the_owner_relays_each_channels_answer_only_to_the_client_that_asked(
    make_endpoint: MakeEndpoint, folder
) -> None:
    owner, first, second = (HoloTabLink(make_endpoint(folder)) for _ in range(3))
    try:
        owner.start()
        extension = hello(owner)
        reader = extension.makefile("rb")
        first.start()
        second.start()
        assert first.wait_connected(WAIT_S) and second.wait_connected(WAIT_S)
        answers_first: list = []
        answers_second: list = []
        workers = [serve_in_thread(first, "one", answers_first), serve_in_thread(second, "two", answers_second)]
        asked = {json.loads(reader.readline())["channel"] for _ in range(2)}
        assert asked == {"one", "two"}
        extension.sendall(json.dumps({"type": "ERROR", "channel": "two", "error": "no tab"}).encode() + b"\n")
        extension.sendall(json.dumps({"type": "SERVING", "channel": "one"}).encode() + b"\n")
        for worker in workers:
            worker.join(WAIT_S)
        assert answers_first == [{"type": "SERVING", "channel": "one"}]
        assert answers_second == [None]
        assert second.last_error == "no tab"
        assert "two" not in first.serving and "one" not in second.serving
    finally:
        for link in (first, second, owner):
            link.close()


def test_a_client_that_exits_has_its_channels_stopped(make_endpoint: MakeEndpoint, folder) -> None:
    owner, client = HoloTabLink(make_endpoint(folder)), HoloTabLink(make_endpoint(folder))
    try:
        owner.start()
        extension = hello(owner)
        reader = extension.makefile("rb")
        client.start()
        assert client.wait_connected(WAIT_S)
        answers: list = []
        worker = serve_in_thread(client, "gone", answers)
        reader.readline()
        extension.sendall(json.dumps({"type": "SERVING", "channel": "gone"}).encode() + b"\n")
        worker.join(WAIT_S)
        client.close()
        assert json.loads(reader.readline()) == {"type": "STOP_CHANNEL", "channel": "gone"}
    finally:
        client.close()
        owner.close()


def test_a_serve_the_owner_cannot_forward_is_refused_to_the_client(make_endpoint: MakeEndpoint, folder) -> None:
    owner, client = HoloTabLink(make_endpoint(folder)), HoloTabLink(make_endpoint(folder))
    try:
        owner.start()
        client.start()
        assert until(lambda: len(owner._peers) == 1)
        assert client.serve("nobody", "http://127.0.0.1:9", "token") is None
        assert client.last_error == "Chrome is not connected through the HoloTab extension"
    finally:
        client.close()
        owner.close()


def test_when_the_owner_exits_a_client_takes_the_endpoint_over(
    make_endpoint: MakeEndpoint, folder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(link_module, "TAKEOVER_PAUSE_S", 0.01)
    owner, first, second = (HoloTabLink(make_endpoint(folder)) for _ in range(3))
    try:
        owner.start()
        first.start()
        second.start()
        assert until(lambda: len(owner._peers) == 2)
        owner.close()
        assert until(lambda: {first.role, second.role} == {"owner", "client"})
        new_owner = first if first.role == "owner" else second
        extension = hello(new_owner)
        assert until(lambda: first.connected and second.connected)
        extension.close()
    finally:
        for link in (first, second, owner):
            link.close()


def test_a_channel_is_asked_for_again_when_the_extension_comes_back_after_a_hand_over(
    make_endpoint: MakeEndpoint, folder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(link_module, "TAKEOVER_PAUSE_S", 0.01)
    owner, client = HoloTabLink(make_endpoint(folder)), HoloTabLink(make_endpoint(folder))
    try:
        owner.start()
        extension = hello(owner)
        reader = extension.makefile("rb")
        client.start()
        assert client.wait_connected(WAIT_S)
        answers: list = []
        worker = serve_in_thread(client, "keep", answers)
        reader.readline()
        extension.sendall(json.dumps({"type": "SERVING", "channel": "keep"}).encode() + b"\n")
        worker.join(WAIT_S)
        owner.close()
        assert until(lambda: client.role == "owner")

        again = hello(client)
        assert json.loads(again.makefile("rb").readline())["channel"] == "keep"
    finally:
        client.close()
        owner.close()


def test_an_error_that_names_only_its_request_reaches_the_client_whose_serve_is_oldest(
    make_endpoint: MakeEndpoint, folder
) -> None:
    owner, client = HoloTabLink(make_endpoint(folder)), HoloTabLink(make_endpoint(folder))
    try:
        owner.start()
        extension = hello(owner)
        reader = extension.makefile("rb")
        client.start()
        assert client.wait_connected(WAIT_S)
        answers: list = []
        worker = serve_in_thread(client, "client-run", answers)
        reader.readline()
        started = time.monotonic()
        extension.sendall(json.dumps({"type": "ERROR", "for": "SERVE_CHANNEL", "error": "no window"}).encode() + b"\n")
        worker.join(WAIT_S)
        assert answers == [None] and time.monotonic() - started < link_module.SERVE_TIMEOUT_S
        assert client.last_error == "no window"
        assert "client-run" not in owner._channel_peer
    finally:
        client.close()
        owner.close()


def test_a_channel_is_asked_for_again_when_the_extension_reconnects_to_the_same_owner(
    make_endpoint: MakeEndpoint, folder
) -> None:
    owner = HoloTabLink(make_endpoint(folder))
    try:
        owner.start()
        extension = hello(owner)
        reader = extension.makefile("rb")
        answers: list = []
        worker = serve_in_thread(owner, "keep", answers)
        reader.readline()
        extension.sendall(json.dumps({"type": "SERVING", "channel": "keep"}).encode() + b"\n")
        worker.join(WAIT_S)
        reader.close()
        extension.close()
        assert until(lambda: not owner.connected and not owner.serving)

        again = hello(owner)
        assert json.loads(again.makefile("rb").readline())["channel"] == "keep"
        again.close()
    finally:
        owner.close()


def test_a_client_counts_a_disconnect_it_was_told_of_as_recent() -> None:
    with short_dir() as path:
        client = HoloTabLink(UnixEndpoint(path / "l.sock"))
        client.extension, client._seen_at = {"id": STORE_EXTENSION_ID, "version": "1.4.11"}, 1.0
        client._handle({"type": "EXTENSION_GONE"})
        assert client.extension is None and client.seen_within(5)


def test_a_client_counts_the_owner_exiting_with_chrome_connected_as_recent(
    make_endpoint: MakeEndpoint, folder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(link_module, "TAKEOVER_PAUSE_S", 0.01)
    owner, client = HoloTabLink(make_endpoint(folder)), HoloTabLink(make_endpoint(folder))
    try:
        owner.start()
        extension = hello(owner)
        client.start()
        assert client.wait_connected(WAIT_S)
        client._seen_at = 1.0
        owner.close()
        assert until(lambda: client.extension is None)
        assert client.seen_within(5)
        extension.close()
    finally:
        client.close()
        owner.close()
