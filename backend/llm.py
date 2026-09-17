import ollama

# Confirmed pulled on this host via `ollama list` (see CONTEXT.md).
MODEL = "mistral-small3.2:24b"

NO_QUESTIONS_SUMMARY = "No questions yet."


def list_installed_models() -> set[str]:
    return {m["model"] for m in ollama.list()["models"]}


def call_local_model(model: str, prompt: str, options: dict | None = None) -> str:
    response = ollama.chat(model=model, messages=[{"role": "user", "content": prompt}], options=options)
    return response["message"]["content"]


def build_summary_prompt(questions: list[str]) -> str:
    numbered = "\n".join(f"{i + 1}. {q}" for i, q in enumerate(questions))
    return f"""You are moderating a live conference Q&A. Below are questions submitted by attendees during the current talk.

Group similar or duplicate questions together, and write a concise summary for the moderator highlighting what the audience most wants addressed. If there is only one question, restate it concisely.

Strict output rules:
- Plain prose only. No markdown, no bullet points, no numbered lists, no bold/italics, no headers.
- 1-3 sentences, under 50 words total.
- Output only the summary text itself, nothing else.

Questions:
{numbered}

Summary:"""


def summarize_questions(questions: list[str]) -> str:
    if not questions:
        return NO_QUESTIONS_SUMMARY
    prompt = build_summary_prompt(questions)
    return call_local_model(MODEL, prompt).strip()


def build_answer_prompt(question: str, context: str = "") -> str:
    # `context` is unused today — a hook for RAG-retrieved material (slides, talk
    # transcript) to be dropped in later without changing this function's shape.
    context_block = f"Reference material:\n{context}\n\n" if context else ""
    return f"""You are ConfCue, an AI assistant answering attendee questions at a conference.

{context_block}Answer the question below as helpfully and concisely as possible. If the question depends on specific facts about this particular event (exact times, venue-specific logistics, speaker-specific details) that you cannot know for certain, say so plainly rather than guessing — suggest they check the schedule/contact page or ask the moderator instead of inventing details.

Question: {question}

Strict output rules:
- Plain prose only. No markdown, no bullet points, no headers.
- 2-4 sentences, under 80 words.
- Output only the answer text itself, nothing else.

Answer:"""


def answer_question(question: str, context: str = "") -> str:
    prompt = build_answer_prompt(question, context)
    # ollama.chat() runs at whatever context window Ollama defaults to
    # (commonly 2048-4096) unless told otherwise — RAG-retrieved chunks plus
    # prompt scaffolding can approach that with no error, just silent
    # truncation. Ask for headroom whenever there's context to lose.
    options = {"num_ctx": 8192} if context else None
    return call_local_model(MODEL, prompt, options).strip()
