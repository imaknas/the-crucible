import asyncio

import numpy as np


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    va, vb = np.array(a), np.array(b)
    denom = np.linalg.norm(va) * np.linalg.norm(vb)
    if denom == 0:
        return 0.0
    return float(np.dot(va, vb) / denom)


def _compute_sync(
    prev_responses: dict[str, str],
    curr_responses: dict[str, str],
    mode: str,
    threshold: float,
) -> tuple[float, bool]:
    """
    Blocking computation — call via run_in_executor from async code.
    Returns (mean_similarity, converged).
    """
    from app.services.rag import get_embeddings

    embeddings = get_embeddings()
    models = [m for m in curr_responses if m in prev_responses]
    if not models:
        return 0.0, False

    similarities = []
    for model_id in models:
        prev_text = prev_responses[model_id].strip()
        curr_text = curr_responses[model_id].strip()
        if not prev_text or not curr_text:
            continue
        prev_vec = embeddings.embed_query(prev_text)
        curr_vec = embeddings.embed_query(curr_text)
        similarities.append(_cosine_similarity(prev_vec, curr_vec))

    if not similarities:
        return 0.0, False

    mean_sim = float(np.mean(similarities))

    if mode == "all":
        converged = all(s >= threshold for s in similarities)
    else:  # "any"
        converged = any(s >= threshold for s in similarities)

    return mean_sim, converged


async def compute_convergence(
    prev_responses: dict[str, str],
    curr_responses: dict[str, str],
    threshold: float = 0.92,
    mode: str = "all",
) -> tuple[float, bool]:
    """
    Async wrapper. Returns (mean_cosine_similarity, converged).
    Runs embedding computation in a thread pool to avoid blocking the event loop.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, _compute_sync, prev_responses, curr_responses, mode, threshold
    )


async def llm_judge_converged(
    graph_app,
    judge_model_id: str,
    thread_id: str,
    round_responses: dict[str, str],
) -> tuple[bool, str]:
    """
    Ask an LLM judge whether the models have reached consensus.
    Returns (converged: bool, reason: str).
    """
    from app.services.graph import get_model, extract_text
    from langchain_core.messages import HumanMessage

    summaries = "\n\n".join(
        f"[{model}]:\n{content}" for model, content in round_responses.items()
    )
    prompt = (
        "You are evaluating whether multiple AI models have reached a substantive consensus.\n\n"
        f"Their responses:\n{summaries}\n\n"
        "Have they converged on the same core position? "
        'Reply with exactly: "CONVERGED: yes, <one-line reason>" or "CONVERGED: no, <one-line reason>".'
    )

    try:
        llm = get_model(judge_model_id, {})
        loop = asyncio.get_running_loop()
        response = await asyncio.wait_for(
            loop.run_in_executor(None, llm.invoke, [HumanMessage(content=prompt)]),
            timeout=30.0,
        )
        text = extract_text(response.content).strip()
        converged = text.upper().startswith("CONVERGED: YES")
        reason = text.split(",", 1)[1].strip() if "," in text else text
        return converged, reason
    except asyncio.TimeoutError:
        return False, "Judge timed out"
    except Exception as e:
        return False, f"Judge error: {e}"
