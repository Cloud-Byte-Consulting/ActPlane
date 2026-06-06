from pathlib import Path

Path(".env").write_text(
    "NVIDIA_NIM_API_KEY=\n"
    "OPENROUTER_API_KEY=\n"
    "MODEL=\"nvidia_nim/nvidia/nemotron-3-super-120b-a12b\"\n"
    "ANTHROPIC_AUTH_TOKEN=\"freecc\"\n",
    encoding="utf-8",
)
