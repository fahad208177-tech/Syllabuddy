"""Check that Amazon Bedrock is ready to be Syllabuddy's brain.

    python scripts/check_bedrock.py

Runs three checks and says how to fix whichever fails:
  1. AWS credentials are found
  2. the model in BEDROCK_MODEL_ID answers a Converse call
  3. it calls a Syllabuddy tool correctly (with the real tool schema)
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from syllabus_core.envfile import load_env  # noqa: E402

load_env()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    from assistant.agent import SYSTEM_PROMPT, BedrockBrain, _simplify_schema

    region = os.environ.get("AWS_REGION", "us-east-1")
    model = os.environ.get("BEDROCK_MODEL_ID", "us.amazon.nova-pro-v1:0")

    # 1. credentials
    try:
        identity = boto3.client("sts", region_name=region).get_caller_identity()
        print(f"[ok] AWS credentials: account {identity['Account']}")
    except (BotoCoreError, ClientError) as error:
        print(f"[fail] No usable AWS credentials ({error}).\n"
              "       Run `aws configure`, or set AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_REGION in .env.")
        return 1

    # 2 + 3. a real tool call, using the same schema the MCP server publishes
    tool = {"name": "check_examinable",
            "description": "Check whether a topic is examinable in the student's A-Level syllabus.",
            "parameters": _simplify_schema({"type": "object", "properties": {
                "topic": {"title": "Topic", "type": "string"},
                "subject": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None}},
                "required": ["topic"]})}
    brain = BedrockBrain(model, region=region)
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": "Is the shortest distance between two skew lines in the H2 Maths syllabus?"}]
    import asyncio

    started = time.perf_counter()
    try:
        reply = asyncio.run(brain.chat(messages, [tool]))
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code", "")
        print(f"[fail] {model} in {region}: {code}: {error}")
        if code == "AccessDeniedException":
            print("       Enable this model under Bedrock console > Model access, or give your IAM user bedrock:InvokeModel.")
        elif code in ("ValidationException", "ResourceNotFoundException"):
            print("       Check BEDROCK_MODEL_ID and AWS_REGION. Cross-region ids look like us.amazon.nova-pro-v1:0.")
        return 1
    seconds = time.perf_counter() - started
    print(f"[ok] {model} answered in {seconds:.1f}s")

    if not reply.tool_calls:
        print(f"[warn] The model replied without calling the tool: {reply.text[:150]!r}\n"
              "       Try a stronger model, e.g. a Claude or Nova Pro inference profile.")
        return 1
    call = reply.tool_calls[0]
    print(f"[ok] Tool call: {call.name}({call.arguments})")
    print("\nBedrock is ready. Set SYLLABUDDY_BRAIN=bedrock in .env and run `python run.py`.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
