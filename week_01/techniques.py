from __future__ import annotations

Msg = dict[str, str]


def is_russian(text: str) -> bool:
    return any("а" <= c.lower() <= "я" for c in text)


_COT = {
    "ru": (
        "\n\nРешай пошагово, объясняя рассуждение на каждом шаге. Заверши чётким финальным ответом."
    ),
    "en": (
        "\n\nSolve step by step, showing your reasoning at each stage. "
        "End with a clear final answer."
    ),
}

_EXPERTS = {
    "ru": (
        "Ты — панель из трёх экспертов, обсуждающих задачу:\n"
        "- Аналитик: смотрит на логику, данные и структуру\n"
        "- Инженер: смотрит на практическую реализацию и компромиссы\n"
        "- Критик: оспаривает допущения и находит слабые места\n\n"
        "Каждый эксперт даёт свою точку зрения, затем панель сходится на финальном ответе."
    ),
    "en": (
        "You are a panel of three experts discussing the problem:\n"
        "- Analyst: focuses on logic, data, and structure\n"
        "- Engineer: focuses on practical implementation and trade-offs\n"
        "- Critic: challenges assumptions and identifies weak points\n\n"
        "Each expert gives their perspective, then the panel agrees on a final answer."
    ),
}

META_STEP1_TEMPLATE = {
    "ru": (
        "Ты эксперт по промпт-инжинирингу.\n"
        "Напиши наилучший промпт для решения следующей задачи. Промпт должен быть "
        "подробным, задавать желаемый формат, стиль рассуждения и ограничения.\n\n"
        "Задача: {question}\n\n"
        "Верни ТОЛЬКО текст промпта, ничего больше."
    ),
    "en": (
        "You are a prompt engineering expert.\n"
        "Write the best possible prompt to solve the following task. The prompt should be "
        "detailed, specify the desired format, reasoning style, and any constraints.\n\n"
        "Task: {question}\n\n"
        "Return ONLY the prompt text, nothing else."
    ),
}

JUDGE_TEMPLATE = {
    "ru": (
        "Ты получил четыре решения одной задачи, каждое — от своей техники промптинга.\n\n"
        "Задача: {question}\n\n"
        "{solutions}\n"
        "Сравни решения. Для каждого оцени: точность, ясность, полноту (1–5). "
        "Затем выбери лучшее и объясни почему в 2–3 предложениях."
    ),
    "en": (
        "You received four solutions to the same task, each produced by a different "
        "prompting technique.\n\n"
        "Task: {question}\n\n"
        "{solutions}\n"
        "Compare the solutions. For each one rate: accuracy, clarity, and completeness (1–5). "
        "Then pick the best overall and explain why in 2–3 sentences."
    ),
}


def direct(question: str) -> list[Msg]:
    return [{"role": "user", "content": question}]


def cot(question: str) -> list[Msg]:
    lang = "ru" if is_russian(question) else "en"
    return [{"role": "user", "content": question + _COT[lang]}]


def experts(question: str) -> list[Msg]:
    lang = "ru" if is_russian(question) else "en"
    return [
        {"role": "system", "content": _EXPERTS[lang]},
        {"role": "user", "content": question},
    ]
