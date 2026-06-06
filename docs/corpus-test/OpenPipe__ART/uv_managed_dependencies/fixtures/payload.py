from pathlib import Path

p = Path("pyproject.toml")
text = p.read_text()
old = 'dependencies = [\n    "openai>=2.14.0",\n'
new = old + '    "requests>=2.32.0",\n'
p.write_text(text.replace(old, new, 1))
