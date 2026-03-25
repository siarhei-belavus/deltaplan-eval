from __future__ import annotations


def choose(prompt: str, options: list[str]) -> str:
    if not options:
        raise ValueError("options required")
    labels = "/".join(options)
    while True:
        print(f"{prompt}")
        print(f"Choices: {labels}")
        choice = input("> ").strip()
        if choice in options:
            return choice
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(options):
                return options[idx]
        print("invalid choice")


def choose_yes_no(prompt: str) -> bool:
    value = choose(prompt, ["Yes", "No"])
    return value == "Yes"
