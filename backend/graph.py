import os
from typing import List, Dict, Optional, Any
from dotenv import load_dotenv
import tiktoken

from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage, BaseMessage
from langgraph.graph import StateGraph, END
from schema import CrucibleState
from routers.models import MODEL_REGISTRY

from utils import extract_text

load_dotenv()


def sanitize_messages(
    messages: List[BaseMessage], prune_history: bool = True
) -> List[BaseMessage]:
    """
    Final Ironclad Sanitizer:
    1. Returns a list of FRESH message objects (no in-place mutation).
    2. Forces ALL content to be non-empty strings.
    3. Merges consecutive same-role messages.
    4. Guarantees User-first and strictly alternating roles.
    5. prune_history: If True, uses the LAST summary marker to jump context.
    """
    from utils import extract_text
    from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

    # --- Step 1: Flatten & Clean to String Content ---
    processed: List[dict] = []  # Use simple dicts for intermediate state
    INDIVIDUAL_CAP = (
        100_000  # Tightened from 500k to prevent Opus 429s (approx 25k tokens)
    )

    for m in messages:
        raw_text = extract_text(m.content)
        # Deep clean noise but preserve basic structure
        clean_text = "".join(c for c in raw_text if c.isprintable() or c in "\n\r\t")

        # Anthropic MUST have non-empty content for EVERY block
        if not clean_text:
            if m.type == "system":
                clean_text = "System Instruction"  # Fallback for empty system
            else:
                continue  # Skip empty user/ai messages

        if len(clean_text) > INDIVIDUAL_CAP:
            clean_text = f"[TRUNCATED]... {clean_text[:INDIVIDUAL_CAP]}"

        # Robust model ID recovery
        model_id = getattr(m, "name", None)
        if not model_id and hasattr(m, "additional_kwargs"):
            model_id = m.additional_kwargs.get("model_id")

        processed.append({"role": m.type, "content": clean_text, "name": model_id})

    if not processed:
        return [HumanMessage(content="Analyze.")]

    # --- Step 2: Handle Summarization Jump (Pruning) ---
    summary_index = -1
    if not prune_history:
        # If the model can handle full history, we keep it all.
        # But we STRIP out any existing summary markers to keep it clean.
        processed = [
            p for p in processed if "PREVIOUS CONTEXT SUMMARY:" not in str(p["content"])
        ]
    else:
        for i, p in enumerate(processed):
            if "PREVIOUS CONTEXT SUMMARY:" in str(p["content"]):
                summary_index = i

    if summary_index != -1:
        print(
            f"[Sanitizer] Found summary at index {summary_index}. Pruning older history."
        )
        # 1. Keep original system messages (instructions)
        sys_messages = [
            p
            for p in processed[:summary_index]
            if p["role"] == "system"
            and "PREVIOUS CONTEXT SUMMARY:" not in str(p["content"])
        ]

        # 2. Key fix: Keep everything FROM the summary onwards
        # This includes any messages added AFTER the summary node ran.
        tail_messages = processed[summary_index:]

        # 3. Message Recovery: If a 'human' message exists immediately BEFORE the summary
        # (e.g. the one that triggered the summary jump), preserve it too.
        recovery = []
        for j in range(max(0, summary_index - 5), summary_index):
            msg = processed[j]
            if msg["role"] == "human" and msg not in tail_messages:
                recovery.append(msg)
                print(
                    f"[Sanitizer] Recovered human message trapped before summary index {j}"
                )

        processed = sys_messages + recovery + tail_messages

    # --- Step 3: Merge Consecutive Roles ---
    merged: List[dict] = []

    # Handle System Messages separately (combine all into one)
    systems = [p for p in processed if p["role"] == "system"]
    others = [p for p in processed if p["role"] != "system"]

    if systems:
        combined_sys = "\n\n".join([str(s["content"]) for s in systems])
        merged.append(
            {"role": "system", "content": combined_sys or "System Instruction"}
        )

    last_role = None
    for p in others:
        if last_role == p["role"]:
            merged[-1]["content"] = f"{merged[-1]['content']}\n\n---\n\n{p['content']}"
            print(f"[Sanitizer] Merged consecutive {p['role']}")
        else:
            merged.append(p)
            last_role = p["role"]

    # --- Step 3: Enforce Total Capacity (1.2M Chars) ---
    TOTAL_LIMIT = 1_200_000
    current_len = sum(len(str(m["content"])) for m in merged if m["role"] == "system")

    allowed_content = []
    content_history = [m for m in merged if m["role"] != "system"]

    for m in reversed(content_history):
        m_len = len(str(m["content"]))
        if current_len + m_len > TOTAL_LIMIT:
            print(
                f"[Sanitizer] Capacity reached. Trimming older history ({m_len} chars dropped)."
            )
            break
        allowed_content.append(m)
        current_len += m_len

    # Reassemble: Systems? + Allowed Messages (restored to chronological order)
    final_list = systems + list(reversed(allowed_content))

    # --- Step 4: Convert to Fresh LangChain Objects ---
    result = []
    for p in final_list:
        role = p["role"]
        # Ensure content is never "" here, just in case
        safe_content = str(p["content"]) or "."
        name = p.get("name")
        kwargs = {"model_id": name} if name else {}

        if role == "system":
            result.append(SystemMessage(content=safe_content))
        elif role == "ai":
            result.append(
                AIMessage(content=safe_content, name=name, additional_kwargs=kwargs)
            )
        else:
            result.append(
                HumanMessage(content=safe_content, name=name, additional_kwargs=kwargs)
            )

    # --- Step 5: Final Opus-specific Guards ---
    # Must have at least one Human/AI message
    if not any(m.type in ("human", "ai") for m in result):
        result.append(HumanMessage(content="Analyzing."))

    # First non-system must be human
    first_non_sys = next((i for i, m in enumerate(result) if m.type != "system"), None)
    if first_non_sys is not None and result[first_non_sys].type == "ai":
        result.insert(first_non_sys, HumanMessage(content="Continue."))

    return result


def get_token_limit(model_id: str) -> int:
    """Return the context soft limit for a specific model ID, default to a safe 60k limit."""
    lower_id = model_id.lower()
    for key, config in MODEL_REGISTRY.items():
        if key in lower_id:
            return config["limit"]
    return 60_000


def count_tokens(messages: list) -> int:
    """Accurately estimate token count for the given message list using cl100k_base."""
    try:
        enc = tiktoken.get_encoding("cl100k_base")
    except Exception:
        enc = tiktoken.encoding_for_model("gpt-4o")

    # Approx 4 tokens overhead per message payload
    total = 0
    for m in messages:
        total += 4
        # handle dicts or BaseMessage objects
        content = (
            m.get("content", "") if isinstance(m, dict) else getattr(m, "content", "")
        )
        if content:
            total += len(enc.encode(str(content)))

    # Anthropic token counting is slightly different. Add 20% safety margin.
    return int(total * 1.2)


_FAMILY_CONSTRUCTORS = {
    "openai": ("OPENAI_API_KEY", ChatOpenAI),
    "anthropic": ("ANTHROPIC_API_KEY", ChatAnthropic),
    "google": ("GOOGLE_API_KEY", ChatGoogleGenerativeAI),
}


def get_model(model_name: str, toggles: Optional[Dict[str, Any]] = None):
    toggles = toggles or {}
    model_name = model_name.strip()
    lower = model_name.lower()

    if lower not in MODEL_REGISTRY:
        raise ValueError(f"Model '{model_name}' is not supported in the whitelist.")

    config = MODEL_REGISTRY[lower]
    env_key, constructor = _FAMILY_CONSTRUCTORS[config["family"]]
    if not os.getenv(env_key):
        raise ValueError(f"{env_key} is not set in environment or .env file.")

    reasoning_kwargs: Dict[str, Any] = {}
    if toggles.get("strict_logic"):
        if config["family"] == "openai":
            reasoning_kwargs["reasoning"] = {
                "effort": "medium",  # Can be "low", "medium", or "high"
                "summary": "auto",  # Can be "auto", "concise", or "detailed"
            }
        elif config["family"] == "anthropic":
            # Native "Adaptive Thinking" is only for flagships (Opus/Sonnet).
            # Haiku/Fast models usually don't support it and would return 400.
            if any(m in config["id"] for m in ["opus", "sonnet"]):
                reasoning_kwargs["thinking"] = {
                    "type": "adaptive",
                }

    return constructor(model=config["id"], **reasoning_kwargs)


def drafting_node(state: CrucibleState):
    """Primary node for building the main argument."""
    active_peer = state["active_peer"]
    model = get_model(active_peer, state.get("toggles", {}))

    # Reasoning enhancement
    prompt_prefix = ""
    if state["toggles"].get("strict_logic"):
        prompt_prefix = "Use Step-by-Step reasoning. "

    # Default role
    role_description = "You are an academic research assistant."

    # Deliberation Mode
    is_delib = state.get("is_deliberation", False)
    if is_delib:
        role_description = (
            f"You are '{active_peer}', a critical reviewer invited to examine the preceding conversation. "
            "The conversation history below is annotated with speaker labels so you can see who said what. "
            "If you previously participated in this conversation, acknowledge your own prior statements and build upon them rather than contradicting yourself. "
            "Analyze the arguments presented so far, highlight any flaws, omissions, or alternative perspectives, "
            "and provide a synthesis or a strong counter-argument to push the deliberation forward."
        )

    # Time & Location Context
    import datetime

    now = datetime.datetime.now()
    time_str = now.strftime("%Y-%m-%d %H:%M:%S")
    tz_str = datetime.datetime.now().astimezone().tzname()
    context_prefix = f"[Current System Time: {time_str} ({tz_str})]\n"

    system_msg = SystemMessage(
        content=f"{context_prefix}{role_description} {prompt_prefix}"
    )

    # Build message list with model attribution for deliberation
    messages: List[BaseMessage] = []
    if is_delib:
        attributed_messages: List[BaseMessage] = [system_msg]
        for msg in state["messages"]:
            # Skip "remove" messages, which are internal signals
            if getattr(msg, "type", "") == "remove":
                continue
            if hasattr(msg, "type") and msg.type == "human":
                # Safely extract text to avoid passing structured content stringified
                content_text = extract_text(msg.content)
                attributed_messages.append(
                    HumanMessage(content=f"[User]: {content_text}")
                )
            elif hasattr(msg, "type") and msg.type == "ai":
                model_name = getattr(msg, "name", None) or "Unknown Model"
                content_text = extract_text(msg.content)
                attributed_messages.append(
                    HumanMessage(content=f"[{model_name}]: {content_text}")
                )
            else:
                attributed_messages.append(msg)
        messages = attributed_messages
    else:
        messages = [system_msg] + list(state["messages"])

    # Selective Pruning: Only prune if the FULL history exceeds this model's limit
    full_tokens = count_tokens(messages)
    limit = get_token_limit(active_peer)

    do_prune = full_tokens > limit
    if do_prune:
        print(
            f"[Selective Pruning] Active for {active_peer} (Full: {full_tokens}, Limit: {limit})"
        )
    else:
        print(
            f"[Selective Pruning] High-fidelity mode for {active_peer} (Full: {full_tokens}, Limit: {limit})"
        )

    sanitized_messages = sanitize_messages(messages, prune_history=do_prune)
    effective_tokens = count_tokens(sanitized_messages)

    # Diagnostic Logging
    print(
        f"\n[INVOKE] Model: {active_peer} | Delib: {is_delib} | Msgs: {len(sanitized_messages)} | Effective Tokens: {effective_tokens}"
    )
    for i, m in enumerate(sanitized_messages):
        c_p = extract_text(m.content)[:60].replace("\n", " ")
        print(f"  {i}: [{m.type}] {c_p}...")

    try:
        response = model.invoke(sanitized_messages)
    except Exception as e:
        print(f"[LLM Error] Node: drafting_node, Model: {active_peer}")
        print(f"[LLM Error] Effective Tokens: {effective_tokens}")
        raise e

    # Tag the response with the model's name for future attribution
    response.name = active_peer
    response.additional_kwargs["model_id"] = active_peer

    # Reset deliberation flag after use
    return {"messages": [response], "is_deliberation": False}


def branching_node(state: CrucibleState):
    """
    Branching logic: This node is a conceptual point where the user
    can switch models or start a new thread based on a checkpoint.
    """
    # In LangGraph, branching is often handled by external thread management.
    # Here we just update the active peer if needed.
    return state


def synthesis_node(state: CrucibleState):
    """Analyzes recent messages to update the 'current_thesis' efficiently."""
    try:
        from utils import extract_text

        messages = state["messages"]
        if not messages:
            return state

        last_msg = messages[-1]
        last_content = extract_text(last_msg.content)

        # Short-circuit: Skip synthesis for trivial turns (e.g. "thanks", "continue")
        if len(last_content) < 20:
            return {"current_thesis": state.get("current_thesis", "")}

        model = get_model(state["active_peer"], state.get("toggles", {}))

        # Optimization: Only use the last 5 messages + the current thesis
        # instead of the entire (potentially large) history.
        recent_context = messages[-5:]
        history_text = "\n".join(
            [f"{m.type}: {extract_text(m.content)}" for m in recent_context]
        )

        current_thesis = state.get("current_thesis", "No thesis identified yet.")

        prompt = (
            "Current Research Thesis:\n"
            f"{current_thesis}\n\n"
            "Recent Conversation Development:\n"
            f"{history_text}\n\n"
            "Task: Refine and update the 'Current Research Thesis' based only on the latest developments. "
            "Keep it concise, rigorous, and academic. Output ONLY the updated thesis text."
        )

        response = model.invoke(sanitize_messages([HumanMessage(content=prompt)]))
        return {"current_thesis": response.content}
    except Exception as e:
        print(f"[Synthesis] failed (non-fatal): {e}")
        return {"current_thesis": state.get("current_thesis", "")}


def summarize_history(state: CrucibleState):
    """Compresses conversation history to fit within model context windows."""
    messages = state["messages"]
    if len(messages) <= 5:
        return {"messages": []}  # No change needed

    # Stop Churn: If the LAST message is already a summary, don't summarize again
    from utils import extract_text

    if messages and "PREVIOUS CONTEXT SUMMARY:" in extract_text(messages[-1].content):
        return {"messages": []}

    model_id = state["active_peer"]
    limit = get_token_limit(model_id)
    current_tokens = count_tokens(messages)

    if current_tokens <= limit:
        return {"messages": []}  # No change needed

    try:
        # Use a FAST model for summarization regardless of the active peer
        # This prevents Opus from stalling the user experience during a summary jump
        from routers.models import MODEL_REGISTRY

        summarizer_id = "gemini-3-flash-preview"
        if summarizer_id not in MODEL_REGISTRY:
            # Fallback to Haiku if Gemini Flash isn't in registry
            summarizer_id = "claude-haiku-4-5-20251001"

        print(f"[Summarize] Using fast model: {summarizer_id} for history compression.")
        model = get_model(summarizer_id, {})

        # Keep the system instruction AND the last 5 messages as-is
        to_summarize = messages[:-5]

        def format_msg(m):
            from utils import extract_text

            content_text = extract_text(m.content)
            if hasattr(m, "type") and m.type == "human":
                return f"[User]: {content_text}"
            elif hasattr(m, "type") and m.type == "ai":
                # Recover name for summary text
                msg_model = getattr(m, "name", None)

                # Priority 2: additional_kwargs
                if not msg_model and hasattr(m, "additional_kwargs"):
                    add_kwargs = getattr(m, "additional_kwargs", {})
                    msg_model = add_kwargs.get(
                        "model", add_kwargs.get("model_id")
                    ) or add_kwargs.get("name")

                # Priority 3: response_metadata
                if not msg_model and hasattr(m, "response_metadata"):
                    resp_meta = getattr(m, "response_metadata", {})
                    msg_model = resp_meta.get(
                        "model_name", resp_meta.get("model_id")
                    ) or resp_meta.get("model")

                return f"[{msg_model or 'AI'}]: {content_text}"
            else:
                return f"[System]: {content_text}"

        history_text = "\n".join([format_msg(m) for m in to_summarize])
        prompt = (
            "Summarize the following conversation history into a concise, detailed technical brief. "
            "IMPORTANT: Preserve the attribution of which speaker (User or specific model name) made each key argument or claim. "
            f"Maintain all key arguments and theses identified so far.\n\n{history_text}"
        )

        # We use a very simplified prompt for the summarizer itself to avoid recursion issues
        summary = model.invoke([HumanMessage(content=prompt)])

        import re

        raw_summary = extract_text(summary.content)
        clean_summary = re.sub(r"\[\{.*?\}\]", "", raw_summary)

        summary_msg = SystemMessage(
            content=f"PREVIOUS CONTEXT SUMMARY: {clean_summary.strip() or 'Context summarized.'}"
        )

        # NON-DESTRUCTIVE: We no longer use RemoveMessage here.
        # This keeps the full history available for large-context models like Gemini.
        # Small-context models will use sanitize_messages() to jump over the summary.
        return {"messages": [summary_msg]}
    except Exception as e:
        print(f"[Summarize] failed (non-fatal): {e}")
        return {"messages": []}


def should_summarize(state: CrucibleState):
    """
    OBSOLETE: Decision logic is now inside summarize_history node
    to simplify graph traversal and prevent accidental infinite loops.
    """
    return "draft"


# BUILD THE GRAPH
workflow = StateGraph(CrucibleState)

workflow.add_node("draft", drafting_node)
workflow.add_node("branch", branching_node)
workflow.add_node("synthesis", synthesis_node)
workflow.add_node("summarize", summarize_history)

# FLOW: Entry -> (Cond) Summarize? -> Draft -> Synthesis -> END
workflow.set_entry_point("summarize")  # We start here, the node logic handles the check

workflow.add_edge("summarize", "draft")
workflow.add_edge("draft", "synthesis")
workflow.add_edge("synthesis", END)

workflow.add_edge("branch", "summarize")

# Persistence configuration is handled in main.py lifespan
