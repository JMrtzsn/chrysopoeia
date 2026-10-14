from google.adk.models import BaseLlm, Gemini, LLMRegistry

from chrysopoeia.configuration import ModelConfig


def resolve_model(config: ModelConfig, model_name: str) -> BaseLlm:
    """Resolve one configured model through the selected ADK model boundary."""
    if config.adapter == "adk-gemini":
        return Gemini(
            model=model_name,
            client_kwargs={"vertexai": True, "location": config.location},
        )
    return LLMRegistry.new_llm(model=model_name)


def resolve_context_model(config: ModelConfig) -> BaseLlm:
    """Google Search grounding requires Vertex Gemini regardless of role adapter."""
    return Gemini(
        model=config.context,
        client_kwargs={"vertexai": True, "location": config.location},
    )
