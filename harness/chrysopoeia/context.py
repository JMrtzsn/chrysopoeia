from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ContextInterface:
    interface_id: str
    description: str
    use_when: str


CONTEXT_INTERFACES = (
    ContextInterface(
        "public_web",
        "Current public information with source links.",
        "A market claim depends on recent events or evidence outside the supplied snapshot.",
    ),
)


def discover_context(task: str) -> list[dict[str, str]]:
    """List context interfaces available for a bounded description of the research task."""
    if not isinstance(task, str) or not task.strip():
        raise ValueError("task must be a non-empty string")
    if len(task) > 1_000:
        raise ValueError("task must not exceed 1,000 characters")
    return [asdict(interface) for interface in CONTEXT_INTERFACES]
