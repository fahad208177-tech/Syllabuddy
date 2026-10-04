"""Drive the running app like a student would and print what happens.

    python scripts/live_check.py "utterance one" "utterance two" ...
"""
import json, sys, time, uuid
import httpx

BASE = "http://127.0.0.1:8000"
session, student = "live-" + uuid.uuid4().hex[:6], "live-student-" + uuid.uuid4().hex[:4]
for text in sys.argv[1:]:
    t = time.time()
    print(f"\n>>> {text}")
    with httpx.stream("POST", f"{BASE}/api/ask", json={"text": text, "session": session, "student": student}, timeout=120) as r:
        for line in r.iter_lines():
            if not line.strip():
                continue
            e = json.loads(line)
            if e["type"] == "tool_call":
                print(f"    tool  {e['name']}({json.dumps(e['arguments'])})")
            elif e["type"] == "tool_result":
                res = e["result"]
                brief = res.get("verdict") or res.get("match") or ("error: " + res["error"] if "error" in res else ", ".join(list(res)[:4]))
                print(f"    ->    {brief}  [{e['ms']} ms]")
            elif e["type"] == "answer":
                print(f"    SAYS  {e['text']}   ({e['seconds']}s)")
            else:
                print("    ERROR", e)
