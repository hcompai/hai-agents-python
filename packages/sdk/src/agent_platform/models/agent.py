from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, BinaryIO, Generator, TextIO, TypeVar, cast

from pydantic import BaseModel, ConfigDict

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.browser import Browser
    from ..models.code_sandbox import CodeSandbox
    from ..models.mcp import MCP
    from ..models.memory import Memory
    from ..models.skill import Skill


T = TypeVar("T", bound="Agent")


class Agent(BaseModel):
    """Declarative agent definition.

    Attributes:
        name (str): Unique catalog identifier for this agent. Format: lowercase ASCII letters, digits and hyphens; must
            start and end with alphanumeric; max 63 chars per segment; optional single 'org/' namespace prefix (e.g. 'h/web-
            environment').
        description (str): Short summary advertised to parent agents that may delegate to this one.
        environments (list[Browser | CodeSandbox | MCP | Memory | str]): Environments the agent runs in. A string entry
            references a catalog id; an inline Environment defines an ad-hoc environment. At least one entry, at most one
            per kind.
        model (None | str | Unset): Model id; defaults to the platform-provided one if omitted.
        instructions (None | str | Unset): Steering text appended to the system prompt.
        subagents (list[Agent | str] | None | Unset): Agents this one can spawn. A string entry references another
            catalog id; an inline Agent defines an ad-hoc sub-agent.
        skills (list[Skill | str] | None | Unset): Skills available to this agent. A string entry references a catalog
            id; an inline Skill defines an ad-hoc skill.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
        arbitrary_types_allowed=True,
    )

    name: str
    description: str
    environments: list[Browser | CodeSandbox | MCP | Memory | str]
    model: None | str | Unset = UNSET
    instructions: None | str | Unset = UNSET
    subagents: list[Agent | str] | None | Unset = UNSET
    skills: list[Skill | str] | None | Unset = UNSET
    additional_properties: dict[str, Any] = {}

    def to_dict(self) -> dict[str, Any]:
        from ..models.browser import Browser
        from ..models.code_sandbox import CodeSandbox
        from ..models.mcp import MCP
        from ..models.memory import Memory
        from ..models.skill import Skill

        name = self.name

        description = self.description

        environments = []
        for environments_item_data in self.environments:
            environments_item: dict[str, Any] | str
            if isinstance(environments_item_data, Browser):
                environments_item = environments_item_data.to_dict()
            elif isinstance(environments_item_data, CodeSandbox):
                environments_item = environments_item_data.to_dict()
            elif isinstance(environments_item_data, MCP):
                environments_item = environments_item_data.to_dict()
            elif isinstance(environments_item_data, Memory):
                environments_item = environments_item_data.to_dict()
            else:
                environments_item = environments_item_data
            environments.append(environments_item)

        model: None | str | Unset
        if isinstance(self.model, Unset):
            model = UNSET
        else:
            model = self.model

        instructions: None | str | Unset
        if isinstance(self.instructions, Unset):
            instructions = UNSET
        else:
            instructions = self.instructions

        subagents: list[dict[str, Any] | str] | None | Unset
        if isinstance(self.subagents, Unset):
            subagents = UNSET
        elif isinstance(self.subagents, list):
            subagents = []
            for subagents_type_0_item_data in self.subagents:
                subagents_type_0_item: dict[str, Any] | str
                if isinstance(subagents_type_0_item_data, Agent):
                    subagents_type_0_item = subagents_type_0_item_data.to_dict()
                else:
                    subagents_type_0_item = subagents_type_0_item_data
                subagents.append(subagents_type_0_item)

        else:
            subagents = self.subagents

        skills: list[dict[str, Any] | str] | None | Unset
        if isinstance(self.skills, Unset):
            skills = UNSET
        elif isinstance(self.skills, list):
            skills = []
            for skills_type_0_item_data in self.skills:
                skills_type_0_item: dict[str, Any] | str
                if isinstance(skills_type_0_item_data, Skill):
                    skills_type_0_item = skills_type_0_item_data.to_dict()
                else:
                    skills_type_0_item = skills_type_0_item_data
                skills.append(skills_type_0_item)

        else:
            skills = self.skills

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "name": name,
                "description": description,
                "environments": environments,
            }
        )
        if model is not UNSET:
            field_dict["model"] = model
        if instructions is not UNSET:
            field_dict["instructions"] = instructions
        if subagents is not UNSET:
            field_dict["subagents"] = subagents
        if skills is not UNSET:
            field_dict["skills"] = skills

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.browser import Browser
        from ..models.code_sandbox import CodeSandbox
        from ..models.mcp import MCP
        from ..models.memory import Memory
        from ..models.skill import Skill

        d = dict(src_dict)
        name = d.pop("name")

        description = d.pop("description")

        environments = []
        _environments = d.pop("environments")
        for environments_item_data in _environments:

            def _parse_environments_item(data: object) -> Browser | CodeSandbox | MCP | Memory | str:
                try:
                    if not isinstance(data, dict):
                        raise TypeError()
                    environments_item_type_1_type_0 = Browser.from_dict(data)

                    return environments_item_type_1_type_0
                except (TypeError, ValueError, AttributeError, KeyError):
                    pass
                try:
                    if not isinstance(data, dict):
                        raise TypeError()
                    environments_item_type_1_type_1 = CodeSandbox.from_dict(data)

                    return environments_item_type_1_type_1
                except (TypeError, ValueError, AttributeError, KeyError):
                    pass
                try:
                    if not isinstance(data, dict):
                        raise TypeError()
                    environments_item_type_1_type_2 = MCP.from_dict(data)

                    return environments_item_type_1_type_2
                except (TypeError, ValueError, AttributeError, KeyError):
                    pass
                try:
                    if not isinstance(data, dict):
                        raise TypeError()
                    environments_item_type_1_type_3 = Memory.from_dict(data)

                    return environments_item_type_1_type_3
                except (TypeError, ValueError, AttributeError, KeyError):
                    pass
                return cast(Browser | CodeSandbox | MCP | Memory | str, data)

            environments_item = _parse_environments_item(environments_item_data)

            environments.append(environments_item)

        def _parse_model(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        model = _parse_model(d.pop("model", UNSET))

        def _parse_instructions(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        instructions = _parse_instructions(d.pop("instructions", UNSET))

        def _parse_subagents(data: object) -> list[Agent | str] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                subagents_type_0 = []
                _subagents_type_0 = data
                for subagents_type_0_item_data in _subagents_type_0:

                    def _parse_subagents_type_0_item(data: object) -> Agent | str:
                        try:
                            if not isinstance(data, dict):
                                raise TypeError()
                            subagents_type_0_item_type_1 = Agent.from_dict(data)

                            return subagents_type_0_item_type_1
                        except (TypeError, ValueError, AttributeError, KeyError):
                            pass
                        return cast(Agent | str, data)

                    subagents_type_0_item = _parse_subagents_type_0_item(subagents_type_0_item_data)

                    subagents_type_0.append(subagents_type_0_item)

                return subagents_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[Agent | str] | None | Unset, data)

        subagents = _parse_subagents(d.pop("subagents", UNSET))

        def _parse_skills(data: object) -> list[Skill | str] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                skills_type_0 = []
                _skills_type_0 = data
                for skills_type_0_item_data in _skills_type_0:

                    def _parse_skills_type_0_item(data: object) -> Skill | str:
                        try:
                            if not isinstance(data, dict):
                                raise TypeError()
                            skills_type_0_item_type_1 = Skill.from_dict(data)

                            return skills_type_0_item_type_1
                        except (TypeError, ValueError, AttributeError, KeyError):
                            pass
                        return cast(Skill | str, data)

                    skills_type_0_item = _parse_skills_type_0_item(skills_type_0_item_data)

                    skills_type_0.append(skills_type_0_item)

                return skills_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[Skill | str] | None | Unset, data)

        skills = _parse_skills(d.pop("skills", UNSET))

        agent = cls(
            name=name,
            description=description,
            environments=environments,
            model=model,
            instructions=instructions,
            subagents=subagents,
            skills=skills,
        )

        agent.additional_properties = d
        return agent

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
