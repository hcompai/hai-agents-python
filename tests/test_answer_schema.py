"""Typed structured output: schema injection and answer parse-back."""

from __future__ import annotations

import typing

import pydantic
import pytest

from hai_agents.polling import (
    AnswerValidationError,
    SessionHandle,
    SessionRunResult,
    _attach_answer_schema,
    run_session,
    wait_for_session,
)


class JobListing(pydantic.BaseModel):
    title: str
    company: str


class JobListings(pydantic.BaseModel):
    jobs: typing.List[JobListing]


_VALID_ANSWER = {"jobs": [{"title": "RE", "company": "H"}, {"title": "SWE", "company": "H"}]}


class _Status:
    def __init__(self, status: str) -> None:
        self.status = status


class _Changes:
    def __init__(self, answer: typing.Any) -> None:
        self.answer = answer
        self.new_events: typing.List[typing.Any] = []


class _Sessions:
    def __init__(self, answer: typing.Any, status: str = "completed") -> None:
        self._answer = answer
        self._status = status
        self.created_with: typing.Optional[dict] = None

    def create_session(self, **kwargs: typing.Any):
        self.created_with = kwargs
        return type("Session", (), {"id": "sess_1"})()

    def get_session_status(self, id: str) -> _Status:
        return _Status(self._status)

    def get_session_changes(self, id: str, **kwargs: typing.Any) -> _Changes:
        return _Changes(self._answer)


class _Client:
    def __init__(self, answer: typing.Any, status: str = "completed") -> None:
        self.sessions = _Sessions(answer, status)


class TestSchemaInjection:
    def test_inline_dict_agent_gets_answer_format(self) -> None:
        params: dict = {"agent": {"name": "a"}}
        _attach_answer_schema(params, JobListings)
        schema = params["agent"]["answer_format"]
        assert schema["title"] == "JobListings"
        assert "JobListing" in schema["$defs"]

    def test_catalog_agent_injected_via_overrides(self) -> None:
        params: dict = {"agent": "h/web-surfer"}
        _attach_answer_schema(params, JobListings)
        assert params["overrides"]["agent.answer_format"]["title"] == "JobListings"

    def test_existing_answer_format_conflicts(self) -> None:
        with pytest.raises(ValueError, match="conflicts"):
            _attach_answer_schema({"agent": {"answer_format": {"type": "object"}}}, JobListings)
        with pytest.raises(ValueError, match="conflicts"):
            _attach_answer_schema({"agent": "h/web-surfer", "overrides": {"agent.answer_format": {}}}, JobListings)

    def test_inline_agent_with_answer_format_override_conflicts(self) -> None:
        with pytest.raises(ValueError, match="conflicts"):
            _attach_answer_schema({"agent": {"name": "a"}, "overrides": {"agent.answer_format": {}}}, JobListings)

    def test_non_model_schema_rejected(self) -> None:
        with pytest.raises(TypeError, match="BaseModel"):
            _attach_answer_schema({"agent": "h/web-surfer"}, dict)

    def test_user_overrides_preserved(self) -> None:
        params: dict = {"agent": "h/web-surfer", "overrides": {"agent.max_steps": 5}}
        _attach_answer_schema(params, JobListings)
        assert params["overrides"]["agent.max_steps"] == 5


class TestAnswerParseBack:
    def test_completed_answer_validates_into_model(self) -> None:
        client = _Client(_VALID_ANSWER)
        result = run_session(client, agent="h/web-surfer", messages="find jobs", answer_schema=JobListings)  # type: ignore[arg-type]
        assert isinstance(result.answer, JobListings)
        assert result.answer.jobs[1].title == "SWE"
        assert client.sessions.created_with["overrides"]["agent.answer_format"]["title"] == "JobListings"
        assert result.final_changes.answer == _VALID_ANSWER

    def test_json_string_answer_parses_into_model(self) -> None:
        client = _Client(JobListings.model_validate(_VALID_ANSWER).model_dump_json())
        result = wait_for_session(client, "sess_1", answer_schema=JobListings)  # type: ignore[arg-type]
        assert isinstance(result.answer, JobListings)
        assert result.answer.jobs[0].title == "RE"

    def test_non_json_string_answer_raises(self) -> None:
        client = _Client("plain text answer")
        with pytest.raises(AnswerValidationError) as exc_info:
            wait_for_session(client, "sess_1", answer_schema=JobListings)  # type: ignore[arg-type]
        assert exc_info.value.raw == "plain text answer"

    def test_nonconforming_answer_raises_with_raw(self) -> None:
        client = _Client({"jobs": "not-a-list"})
        with pytest.raises(AnswerValidationError) as exc_info:
            wait_for_session(client, "sess_1", answer_schema=JobListings)  # type: ignore[arg-type]
        assert exc_info.value.raw == {"jobs": "not-a-list"}

    def test_non_completed_status_passes_raw_through(self) -> None:
        client = _Client("cancelled mid-run", status="interrupted")
        result = wait_for_session(client, "sess_1", answer_schema=JobListings)  # type: ignore[arg-type]
        assert result.answer == "cancelled mid-run"

    def test_completed_none_answer_raises(self) -> None:
        client = _Client(None)
        with pytest.raises(AnswerValidationError) as exc_info:
            wait_for_session(client, "sess_1", answer_schema=JobListings)  # type: ignore[arg-type]
        assert exc_info.value.raw is None

    def test_non_completed_none_answer_passes_through(self) -> None:
        client = _Client(None, status="failed")
        result = wait_for_session(client, "sess_1", answer_schema=JobListings)  # type: ignore[arg-type]
        assert result.answer is None

    def test_no_schema_keeps_raw_answer(self) -> None:
        client = _Client(_VALID_ANSWER)
        result = wait_for_session(client, "sess_1")  # type: ignore[arg-type]
        assert result.answer == _VALID_ANSWER


class TestComposesWithTools:
    def test_schema_and_tools_attach_independent_overrides(self) -> None:
        def get_weather(city: str) -> str:
            """Get the weather."""
            return "sunny"

        client = _Client(_VALID_ANSWER)
        result = run_session(  # type: ignore[arg-type]
            client, agent="h/web-surfer", messages="go", answer_schema=JobListings, tools=[get_weather]
        )
        overrides = client.sessions.created_with["overrides"]
        assert overrides["agent.answer_format"]["title"] == "JobListings"
        assert overrides["agent.tools"][0]["name"] == "get_weather"
        assert isinstance(result.answer, JobListings)


class TestSessionHandle:
    def test_handle_carries_schema_into_wait_for_completion(self) -> None:
        client = _Client(_VALID_ANSWER)
        handle = SessionHandle(client, "sess_1", answer_schema=JobListings)  # type: ignore[arg-type]
        result = handle.wait_for_completion()
        assert isinstance(result.answer, JobListings)

    def test_explicit_none_disables_handle_schema(self) -> None:
        client = _Client(_VALID_ANSWER)
        handle = SessionHandle(client, "sess_1", answer_schema=JobListings)  # type: ignore[arg-type]
        result = handle.wait_for_completion(answer_schema=None)
        assert result.answer == _VALID_ANSWER


class TestSessionRunResultBackfill:
    def test_answer_backfills_from_final_changes(self) -> None:
        result = SessionRunResult(
            id="s", status="completed", events=[], next_from_index=0, final_changes=_Changes("done")
        )
        assert result.answer == "done"
