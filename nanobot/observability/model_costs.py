"""Model cost catalog with LiteLLM fallback."""

from __future__ import annotations

# Costs per 1 million tokens (USD).
# Maintained manually for the most popular models; LiteLLM covers the long tail.
MODEL_COSTS: dict[str, dict[str, float]] = {
    # Anthropic
    "anthropic/claude-opus-4-5": {"input": 15.0, "output": 75.0},
    "anthropic/claude-sonnet-4-5": {"input": 3.0, "output": 15.0},
    "anthropic/claude-sonnet-4": {"input": 3.0, "output": 15.0},
    "anthropic/claude-haiku-4-5": {"input": 0.80, "output": 4.0},
    "claude-opus-4-5-20250514": {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-5-20250514": {"input": 3.0, "output": 15.0},
    "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.0},
    # OpenAI
    "openai/gpt-4o": {"input": 2.50, "output": 10.0},
    "openai/gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "openai/gpt-4.1": {"input": 2.0, "output": 8.0},
    "openai/gpt-4.1-mini": {"input": 0.40, "output": 1.60},
    "openai/gpt-4.1-nano": {"input": 0.10, "output": 0.40},
    "openai/o3": {"input": 10.0, "output": 40.0},
    "openai/o3-mini": {"input": 1.10, "output": 4.40},
    "openai/o4-mini": {"input": 1.10, "output": 4.40},
    # Google
    "gemini/gemini-2.5-pro": {"input": 1.25, "output": 10.0},
    "gemini/gemini-2.5-flash": {"input": 0.15, "output": 0.60},
    "gemini/gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    # DeepSeek
    "deepseek/deepseek-chat": {"input": 0.27, "output": 1.10},
    "deepseek/deepseek-reasoner": {"input": 0.55, "output": 2.19},
    # Qwen
    "openrouter/qwen/qwen-2.5-72b-instruct": {"input": 0.36, "output": 0.36},
}


def get_model_cost(model: str) -> tuple[float, float] | None:
    """Return (input_cost_per_1m, output_cost_per_1m) for *model*, or None."""
    # 1. Exact match in local catalog
    if model in MODEL_COSTS:
        c = MODEL_COSTS[model]
        return c["input"], c["output"]

    # 2. Try without provider prefix (e.g. "claude-opus-4-5-20250514")
    if "/" in model:
        short = model.split("/", 1)[1]
        if short in MODEL_COSTS:
            c = MODEL_COSTS[short]
            return c["input"], c["output"]

    # 3. Fallback to LiteLLM's comprehensive cost database
    try:
        from litellm import model_cost as _litellm_costs  # type: ignore[import-untyped]

        entry = _litellm_costs.get(model)
        if entry:
            return (
                entry.get("input_cost_per_token", 0) * 1_000_000,
                entry.get("output_cost_per_token", 0) * 1_000_000,
            )
        # Also try the short name
        if "/" in model:
            entry = _litellm_costs.get(model.split("/", 1)[1])
            if entry:
                return (
                    entry.get("input_cost_per_token", 0) * 1_000_000,
                    entry.get("output_cost_per_token", 0) * 1_000_000,
                )
    except Exception:
        pass

    return None


def compute_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cached_tokens: int = 0,
) -> float | None:
    """Compute USD cost for a single LLM call.  Returns None if model cost is unknown."""
    costs = get_model_cost(model)
    if costs is None:
        return None
    input_per_1m, output_per_1m = costs
    # Cached input tokens are typically 90% cheaper (Anthropic) or free (OpenAI).
    # Use 10% of input price as a reasonable default.
    billable_input = prompt_tokens - cached_tokens
    cached_cost = cached_tokens * (input_per_1m * 0.1) / 1_000_000
    input_cost = billable_input * input_per_1m / 1_000_000
    output_cost = completion_tokens * output_per_1m / 1_000_000
    return input_cost + cached_cost + output_cost
