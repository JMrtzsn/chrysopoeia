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
    """Resolve the research model through the same provider boundary as every role."""
    return resolve_model(config, config.context)


def supports_grounding(model: BaseLlm) -> bool:
    """Only Google Gemini models expose the bounded Google Search grounding tool."""
    return isinstance(model, Gemini)


def resolve_research_provider(config: ModelConfig) -> str:
    """Select the research provider implied by the configured context model."""
    if config.context.startswith("openrouter/"):
        return "openrouter-web"
    if config.context.startswith("gemini-"):
        return "google-search"
    return "none"
