from __future__ import annotations


def choose(prompt: str, options: list[str]) -> str:
    if not options:
        raise ValueError("options required")

    labels = "/".join(options)
    normalized = {option.casefold(): option for option in options}
    is_yes_no = [option.casefold() for option in options] == ["yes", "no"]

    while True:
        print(f"{prompt}")
        if is_yes_no:
            print(f"Choices: {labels} [default: {options[0]}]")
        else:
            print(f"Choices: {labels}")

        choice = input("> ").strip()
        if not choice and is_yes_no:
            return options[0]
        if choice in options:
            return choice

        folded = choice.casefold()
        if folded in normalized:
            return normalized[folded]
        if is_yes_no and folded in {"y", "yes"}:
            return options[0]
        if is_yes_no and folded in {"n", "no"}:
            return options[1]
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(options):
                return options[idx]
        print("invalid choice")


def choose_yes_no(prompt: str) -> bool:
    value = choose(prompt, ["Yes", "No"])
    return value == "Yes"
