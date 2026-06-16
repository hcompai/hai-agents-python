"""Unit tests for local_desktop — no network, no pyautogui required."""

import ast
import base64
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

import hai_agents
import hai_agents.local_desktop as local_desktop
from hai_agents.local_desktop import (
    LocalDesktopClient,
    LocalDesktopClientConfig,
    _deserialize_args,
    _serialize_result,
    session_id_from_environment_id,
)


class TestSessionIdFromEnvironmentId:
    def test_deterministic(self):
        assert session_id_from_environment_id("my-mac", "key") == session_id_from_environment_id("my-mac", "key")

    def test_different_environment_id_gives_different_result(self):
        assert session_id_from_environment_id("mac-a", "key") != session_id_from_environment_id("mac-b", "key")

    def test_different_api_key_gives_different_result(self):
        assert session_id_from_environment_id("mac", "key-a") != session_id_from_environment_id("mac", "key-b")

    def test_returns_valid_uuid_string(self):
        import uuid

        sid = session_id_from_environment_id("my-mac", "key")
        uuid.UUID(sid)  # raises ValueError if not a valid UUID

    def test_root_export_is_available_at_runtime(self):
        from hai_agents import session_id_from_environment_id as root_session_id_from_environment_id

        assert root_session_id_from_environment_id is session_id_from_environment_id

    def test_root_export_is_available_for_type_checkers(self):
        source = Path(hai_agents.__file__).read_text()
        module = ast.parse(source)

        type_checking_imports: set[str] = set()
        for node in module.body:
            if not isinstance(node, ast.If):
                continue
            test = node.test
            is_type_checking_block = (
                isinstance(test, ast.Attribute)
                and isinstance(test.value, ast.Name)
                and test.value.id == "typing"
                and test.attr == "TYPE_CHECKING"
            )
            if not is_type_checking_block:
                continue
            for statement in node.body:
                if isinstance(statement, ast.ImportFrom) and statement.module == "local_desktop":
                    type_checking_imports.update(alias.name for alias in statement.names)

        assert "session_id_from_environment_id" in type_checking_imports


class TestLocalDesktopClientConfig:
    def test_derives_session_id_automatically(self):
        config = LocalDesktopClientConfig(environment_id="my-mac", api_key="test-key")
        assert config.session_id == session_id_from_environment_id("my-mac", "test-key")

    def test_explicit_session_id_not_overridden(self):
        config = LocalDesktopClientConfig(environment_id="my-mac", api_key="key", session_id="custom-id")
        assert config.session_id == "custom-id"

    def test_reads_api_key_from_agp_api_key_env(self, monkeypatch):
        monkeypatch.delenv("AGP_SERVICE_KEY", raising=False)
        monkeypatch.setenv("AGP_API_KEY", "env-key")
        config = LocalDesktopClientConfig(environment_id="my-mac")
        assert config.api_key == "env-key"

    def test_agp_service_key_takes_priority_over_api_key(self, monkeypatch):
        monkeypatch.setenv("AGP_SERVICE_KEY", "service-key")
        monkeypatch.setenv("AGP_API_KEY", "api-key")
        config = LocalDesktopClientConfig(environment_id="my-mac")
        assert config.api_key == "service-key"

    def test_missing_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("AGP_SERVICE_KEY", raising=False)
        monkeypatch.delenv("AGP_API_KEY", raising=False)
        with pytest.raises(ValueError, match="api_key is required"):
            LocalDesktopClientConfig(environment_id="my-mac")


class TestSerializeResult:
    def test_bytes_become_base64_string(self):
        result = _serialize_result(b"\x89PNG\r\n")
        assert isinstance(result, str)
        assert base64.b64decode(result) == b"\x89PNG\r\n"

    def test_none_passes_through(self):
        assert _serialize_result(None) is None

    def test_primitives_pass_through(self):
        assert _serialize_result(42) == 42
        assert _serialize_result("hello") == "hello"
        assert _serialize_result(True) is True

    def test_pydantic_model_dumps_to_json_dict(self):
        from pydantic import BaseModel

        class M(BaseModel):
            x: int = 1
            y: str = "a"

        assert _serialize_result(M()) == {"x": 1, "y": "a"}

    def test_list_items_recursively_serialized(self):
        result = _serialize_result([b"abc", 1, None])
        assert base64.b64decode(result[0]) == b"abc"
        assert result[1] == 1
        assert result[2] is None

    def test_tuple_items_recursively_serialized(self):
        result = _serialize_result((1920, 1080))
        assert result == [1920, 1080]


class TestDeserializeArgs:
    def test_write_file_content_decoded_from_base64(self):
        encoded = base64.b64encode(b"hello world").decode()
        result = _deserialize_args("write_file", {"path": "/tmp/f.txt", "content": encoded})
        assert result["content"] == b"hello world"
        assert result["path"] == "/tmp/f.txt"

    def test_non_write_file_commands_unchanged(self):
        args = {"x": 100, "y": 200, "button": "left"}
        assert _deserialize_args("click", args) == args

    def test_run_command_cwd_string_converted_to_path(self):
        result = _deserialize_args("run_command", {"command": ["ls"], "cwd": "/tmp"})
        assert result["cwd"] == Path("/tmp")

    def test_run_command_none_cwd_left_as_none(self):
        result = _deserialize_args("run_command", {"command": ["ls"], "cwd": None})
        assert result["cwd"] is None

    def test_write_file_non_string_content_untouched(self):
        # If content is already bytes (shouldn't happen in practice, but guard it)
        result = _deserialize_args("write_file", {"path": "/f", "content": b"raw"})
        assert result["content"] == b"raw"


class TestLocalDesktopDriverRunCommand:
    def test_detach_on_posix_starts_new_session_and_disconnects_stdio(self, monkeypatch):
        calls = []

        def fake_popen(command, **kwargs):
            calls.append((command, kwargs))
            return SimpleNamespace()

        monkeypatch.setattr(local_desktop.os, "name", "posix")
        monkeypatch.setattr(local_desktop.subprocess, "Popen", fake_popen)

        driver = local_desktop._LocalDesktopDriver()
        result = driver.run_command(
            ["sleep", "10"],
            env={"EXAMPLE": "1"},
            cwd=Path("/tmp"),
            detach=True,
        )

        assert result.returncode == 0
        assert result.stdout == ""
        assert result.stderr == ""
        assert calls == [
            (
                ["sleep", "10"],
                {
                    "env": {"EXAMPLE": "1"},
                    "cwd": Path("/tmp"),
                    "stdin": local_desktop.subprocess.DEVNULL,
                    "stdout": local_desktop.subprocess.DEVNULL,
                    "stderr": local_desktop.subprocess.DEVNULL,
                    "close_fds": True,
                    "start_new_session": True,
                },
            )
        ]

    def test_detach_on_windows_uses_detached_process_flags(self, monkeypatch):
        calls = []

        def fake_popen(command, **kwargs):
            calls.append((command, kwargs))
            return SimpleNamespace()

        monkeypatch.setattr(local_desktop.os, "name", "nt")
        monkeypatch.setattr(local_desktop.subprocess, "Popen", fake_popen)

        driver = local_desktop._LocalDesktopDriver()
        result = driver.run_command(["cmd", "/c", "start"], detach=True)

        assert result.returncode == 0
        assert calls == [
            (
                ["cmd", "/c", "start"],
                {
                    "env": None,
                    "cwd": None,
                    "stdin": local_desktop.subprocess.DEVNULL,
                    "stdout": local_desktop.subprocess.DEVNULL,
                    "stderr": local_desktop.subprocess.DEVNULL,
                    "close_fds": True,
                    "creationflags": local_desktop._WINDOWS_DETACHED_PROCESS
                    | local_desktop._WINDOWS_CREATE_NEW_PROCESS_GROUP,
                },
            )
        ]


class _FakeDriver:
    """Minimal driver stub that records calls and returns configurable values."""

    def __init__(self):
        self._calls: list = []
        self.click_returns = None
        self.screenshot_returns = b"\x89PNG"

    def click(self, x: int, y: int, button: str = "left") -> None:
        self._calls.append(("click", x, y, button))
        return self.click_returns

    def screenshot_png_bytes(self) -> bytes:
        self._calls.append(("screenshot_png_bytes",))
        return self.screenshot_returns

    def get_accessibility_tree(self) -> str:
        raise NotImplementedError("not supported")


class TestLocalDesktopClientDispatch:
    def _make_client(self, driver=None):
        config = LocalDesktopClientConfig(environment_id="my-mac", api_key="key")
        return LocalDesktopClient(config, driver=driver or _FakeDriver())

    def test_dispatches_method_by_name(self):
        driver = _FakeDriver()
        client = self._make_client(driver)
        result, error = client._dispatch("click", {"x": 10, "y": 20})
        assert error is None
        assert driver._calls == [("click", 10, 20, "left")]

    def test_unknown_method_returns_error(self):
        client = self._make_client()
        result, error = client._dispatch("no_such_method", {})
        assert result is None
        assert "Unknown command" in error

    def test_not_implemented_method_returns_error(self):
        client = self._make_client()
        result, error = client._dispatch("get_accessibility_tree", {})
        assert result is None
        assert "not supported" in error

    def test_driver_exception_returned_as_error_string(self):
        driver = SimpleNamespace(explode=lambda **_: (_ for _ in ()).throw(RuntimeError("boom")))
        client = self._make_client(driver)
        result, error = client._dispatch("explode", {})
        assert result is None
        assert "boom" in error

    def test_screenshot_bytes_serialized_to_base64(self):
        driver = _FakeDriver()
        client = self._make_client(driver)
        result, error = client._dispatch("screenshot_png_bytes", {})
        assert error is None
        assert base64.b64decode(result) == b"\x89PNG"


class _FakeHttpClient:
    def __init__(self, get_response: httpx.Response, post_response: httpx.Response):
        self.get_response = get_response
        self.post_response = post_response

    async def get(self, *args, **kwargs):
        return self.get_response

    async def post(self, *args, **kwargs):
        return self.post_response


class TestLocalDesktopClientEnsureSession:
    def _make_client(self):
        config = LocalDesktopClientConfig(environment_id="my-mac", api_key="key", base_url="https://example.test")
        return LocalDesktopClient(config, driver=_FakeDriver())

    def _response(self, status_code: int) -> httpx.Response:
        request = httpx.Request("POST", "https://example.test/api/v1/trajectories/")
        return httpx.Response(status_code, request=request)

    async def test_create_session_non_success_raises_clear_http_error(self):
        client = self._make_client()
        http_client = _FakeHttpClient(
            get_response=self._response(404),
            post_response=self._response(500),
        )

        with pytest.raises(httpx.HTTPStatusError, match="500"):
            await client._ensure_session(http_client)
