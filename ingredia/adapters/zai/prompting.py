"""Keep the existing GLM prompt interface backed by common extraction resources."""

from string import Template

from ingredia.recognition.prompting import prompt_template, render_prompt


def photo_prompt_template() -> Template:
    """Return the shared photo template for compatibility."""
    return prompt_template("food_photo")


def render_photo_prompt() -> str:
    """Render the existing photo prompt without provider-dependent domain rules."""
    return render_prompt("food_photo")
