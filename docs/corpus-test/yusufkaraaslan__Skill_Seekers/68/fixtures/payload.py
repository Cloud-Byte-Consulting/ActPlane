from pathlib import Path
import subprocess

p = Path(".env")
p.write_text("OPENAI_API_KEY=sk_test_actplane_fixture_only\n", encoding="utf-8")
_ = p.read_text(encoding="utf-8")
subprocess.run(["git", "add", "-f", ".env"], check=True)
