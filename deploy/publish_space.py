"""Publish Syllabuddy as a Hugging Face Docker Space.

    pip install huggingface_hub
    set HF_TOKEN=hf_...              (a "write" token from huggingface.co/settings/tokens)
    python deploy/publish_space.py [--space syllabuddy] [--private]

Creates (or updates) https://huggingface.co/spaces/<you>/<space>, uploads the
code, data and Dockerfile, and copies the model settings from your local .env
into the Space: the API key as a secret, the rest as variables. Nothing secret
is printed. The Space then builds itself (about 5 to 10 minutes) and serves the
web app at https://<you>-<space>.hf.space and MCP at .../mcp.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from syllabus_core.envfile import load_env  # noqa: E402

FILES = ["Dockerfile", "requirements.txt", "LICENSE"]
FOLDERS = ["syllabus_core", "mcp_server", "assistant", "deploy", "alexa-addon/media"]
DATA = ["*.json", "embeddings-*.npz"]
SECRETS = ["SYLLABUDDY_LLM_API_KEY"]
VARIABLES = ["SYLLABUDDY_BRAIN", "SYLLABUDDY_LLM_BASE_URL", "SYLLABUDDY_LLM_MODEL", "SYLLABUDDY_LLM_REASONING"]


def stage(target: Path) -> None:
    """Copy exactly what the image needs; never .env, the progress database or caches."""
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "*.db")
    for name in FILES:
        shutil.copy2(ROOT / name, target / name)
    for folder in FOLDERS:
        shutil.copytree(ROOT / folder, target / folder, ignore=ignore)
    (target / "data").mkdir()
    for pattern in DATA:
        for path in (ROOT / "data").glob(pattern):
            shutil.copy2(path, target / "data" / path.name)
    shutil.copy2(ROOT / "deploy" / "huggingface" / "README.md", target / "README.md")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--space", default="syllabuddy")
    parser.add_argument("--private", action="store_true")
    args = parser.parse_args()

    try:
        from huggingface_hub import HfApi
    except ImportError:
        print("Install it first: pip install huggingface_hub")
        return 1
    load_env()
    token = os.environ.get("HF_TOKEN")
    if not token:
        print("Set HF_TOKEN to a write token from https://huggingface.co/settings/tokens")
        return 1
    api = HfApi(token=token)
    user = api.whoami()["name"]
    repo_id = f"{user}/{args.space}"
    api.create_repo(repo_id, repo_type="space", space_sdk="docker", private=args.private, exist_ok=True)

    for key in SECRETS:
        if os.environ.get(key):
            api.add_space_secret(repo_id, key, os.environ[key])
            print(f"secret   {key} set")
    for key in VARIABLES:
        if os.environ.get(key):
            api.add_space_variable(repo_id, key, os.environ[key])
            print(f"variable {key} = {os.environ[key]}")

    with tempfile.TemporaryDirectory() as tmp:
        stage(Path(tmp))
        api.upload_folder(repo_id=repo_id, repo_type="space", folder_path=tmp,
                          commit_message="Deploy Syllabuddy", delete_patterns=["*"])
    host = f"{user}-{args.space}".lower().replace("_", "-")
    print(f"\nUploaded. Building now (5 to 10 minutes): https://huggingface.co/spaces/{repo_id}")
    print(f"Web app:  https://{host}.hf.space")
    print(f"MCP:      https://{host}.hf.space/mcp")
    return 0


if __name__ == "__main__":
    sys.exit(main())
