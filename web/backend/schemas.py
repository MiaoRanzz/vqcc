"""HTTP input contracts. Algorithm bounds live with the job dispatcher."""
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')


class SessionInput(Input):
    key: str


class JobInput(Input):
    kind: Literal['local_experiment', 'local_validate', 'local_promote', 'prepare_preview',
                  'optimize', 'smoke', 'submit', 'reconcile']
    task: Literal['dqi', 'invsqrt', 'dfthcsos'] | None = None
    parent_candidate_id: str | None = None
    candidate_id: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    dataset_id: str | None = None
    generator_revision: str | None = None
    hypothesis: str = ''
    max_seconds: int = 1200
    run_validation: bool = Field(True, alias='validate')
    robustness: bool = False
    model: str | None = None
    reasoning: str | None = None
    service_tier: str | None = None
    research_id: str | None = None
    allow_subagents: bool = False


class CancelInput(Input):
    expected_state: Literal['queued', 'blocked']
    revision: int


class StopInput(Input):
    run_id: str
    revision: int


class ConfigInput(Input):
    config: dict[str, Any]
    expected_revision: int


class ActivateInput(Input):
    revision: int
    expected_revision: int


class ResearchInput(Input):
    status: Literal['pending', 'running', 'supported', 'rejected', 'inconclusive', 'unverified', 'disabled']
    priority: int = Field(ge=0)
    notes: str = ''
    experiment_ids: list[str] = Field(default_factory=list)
    expected_revision: int
