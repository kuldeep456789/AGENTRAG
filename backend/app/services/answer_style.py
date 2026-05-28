from __future__ import annotations

import re


def _is_coding_query(query: str) -> bool:
    lowered = query.lower()
    coding_terms = {
        "api", "code", "coding", "debug", "dsa", "exception", "function", "implement",
        "javascript", "python", "react", "script", "stack trace", "traceback", "typescript",
    }
    return any(term in lowered for term in coding_terms)

BRIEF_ANSWER_RULES = (
    "\nAnswer style: BRIEF"
    "\n- Keep the whole answer under 130 words unless the user explicitly asked for more."
    "\n- Use 3–4 short paragraphs only. No ## headings and no long bullet lists."
    "\n- Open with **Key term** followed by one clear definition sentence using an em dash (—) when helpful."
    "\n- Use *italic* sparingly (1–2 words) for emphasis."
    "\n- Include one line that starts with **Example:** and uses → to show cause and effect."
    "\n- End with a short closing line such as \"That's the core idea.\""
    "\n- Do NOT start with \"Here is what I found.\""
)

DETAILED_ANSWER_RULES = (
    "\nAnswer style: DETAILED"
    "\n- Teach clearly using ## section headings (e.g. ## The core idea, ## How it works, ## Main types)."
    "\n- Use short paragraphs plus bullet lists; bold the label in each bullet (e.g. **Supervised learning** — ...)."
    "\n- Add comparison lines when useful, e.g. Traditional programming: Data + Rules → Output"
    "\n- Cover definitions, how it works, types, examples, and real-world use cases when relevant."
    "\n- You may end with one optional line offering to go deeper on a sub-topic."
    "\n- Do NOT start with \"Here is what I found.\""
)

CODING_ANSWER_RULES = (
    "\nAnswer style: CODING"
    "\n- Short explanation, then fenced ```language blocks with one statement per line."
    "\n- Use **bold** for key terms and bullet lists when comparing approaches."
    "\n- After examples, add Output: and a ```output fence when there is sample output."
)

BRIEF_QUERY_PATTERNS = (
    r"\bin short\b",
    r"\bin brief\b",
    r"\bbriefly\b",
    r"\bquick(ly)?\b",
    r"\bsimple terms\b",
    r"\bsimply\b",
    r"\beli5\b",
    r"\btldr\b",
    r"\bone[- ]liner\b",
    r"\bfew words\b",
    r"\bshort answer\b",
    r"\bexplain simply\b",
)

DETAILED_QUERY_PATTERNS = (
    r"\bwhat is\b",
    r"\bwhat are\b",
    r"\bhow does\b",
    r"\bhow do\b",
    r"\bwhy does\b",
    r"\bexplain\b",
    r"\btell me about\b",
    r"\bdescribe\b",
    r"\boverview\b",
    r"\bin detail\b",
    r"\bcomprehensive\b",
    r"\bfull guide\b",
    r"\beverything about\b",
)


def infer_answer_style(query: str) -> str:
    if _is_coding_query(query):
        return "coding"

    lowered = query.lower().strip()
    if any(re.search(pattern, lowered) for pattern in BRIEF_QUERY_PATTERNS):
        return "brief"
    if any(re.search(pattern, lowered) for pattern in DETAILED_QUERY_PATTERNS):
        return "detailed"

    word_count = len(lowered.split())
    if word_count <= 6 and not re.search(r"\bwhat\b|\bhow\b|\bwhy\b", lowered):
        return "brief"
    if word_count >= 10:
        return "detailed"
    return "brief" if word_count <= 8 else "detailed"


def style_rules(style: str) -> str:
    if style == "coding":
        return CODING_ANSWER_RULES
    if style == "brief":
        return BRIEF_ANSWER_RULES
    return DETAILED_ANSWER_RULES


def prompt_rules_for_style(style: str, *, rag: bool = False) -> str:
    """System-prompt formatting rules for a given answer style."""
    rules = style_rules(style)
    if rag:
        rules += (
            "\n- When context is provided, ground the answer in it and mention the source/page when relevant."
        )
    if style == "detailed":
        rules += (
            "\n- Use clean GitHub-Flavored Markdown: ## headings, short paragraphs, bullet lists, fenced ```language code blocks."
        )
    elif style == "coding":
        rules += "\n- Put each statement on its own line inside code fences; never collapse code into one line."
    return rules
