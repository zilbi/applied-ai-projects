from pathlib import Path


TEMPLATES_DIR = Path("templates")


def list_templates():
    if not TEMPLATES_DIR.exists():
        return []
    return sorted(path.name for path in TEMPLATES_DIR.glob("*.txt"))


def load_template(template_name):
    path = TEMPLATES_DIR / template_name
    if not path.is_file():
        raise FileNotFoundError(f"Template not found: {template_name}")
    return path.read_text(encoding="utf-8")


def render_template(template_name, context):
    return load_template(template_name).format(**context)
