import re


def clean_llm_response(response_text: str) -> str:
    # This pattern matches:
    # 1. Start with ```json (or just ```)
    # 2. Capture everything inside (.*?)
    # 3. End with ```
    # re.DOTALL allows the dot (.) to match newlines
    pattern = r"^```(?:json)?\s*(.*?)\s*```$"

    match = re.search(pattern, response_text.strip(), re.DOTALL)

    if match:
        return match.group(1)

    # If no tags are found, return the original string
    return response_text
