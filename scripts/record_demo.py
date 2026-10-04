"""Record a clean screen capture of the real app running the demo script.

    python run.py                      # in another terminal, with your chosen brain
    python scripts/record_demo.py      # needs: pip install playwright imageio-ffmpeg

Saves artifacts/demo_capture.mp4 (silent: add your voice-over, see docs/DEMO_SCRIPT.md).
Questions are typed at dictation speed so viewers can read them.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "artifacts"
SIZE = {"width": 1600, "height": 900}
SCRIPT = [
    "Is the shortest distance between two skew lines on the H2 Maths exam?",
    "What about the distance from a point to a plane?",
    "Do I need to know Type II error for H2 Maths?",
    "Quiz me on H2 Physics",
    None,  # answer the quiz (filled in below)
    "What should I revise first?",
]
QUIZ_ANSWER = "I'm not sure, can you tell me?"


def say(page, text: str) -> None:
    before = page.locator(".turn.answer").count()
    page.click("#text")
    page.keyboard.type(text, delay=45)
    page.wait_for_timeout(400)
    page.keyboard.press("Enter")
    page.wait_for_function(f"document.querySelectorAll('.turn.answer').length > {before}", timeout=180000)
    page.wait_for_timeout(4500)  # let viewers read the answer and card


def main() -> int:
    OUT.mkdir(exist_ok=True)
    raw = OUT / "raw_video"
    shutil.rmtree(raw, ignore_errors=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        context = browser.new_context(viewport=SIZE, record_video_dir=str(raw), record_video_size=SIZE)
        page = context.new_page()
        page.goto("http://127.0.0.1:8000")
        page.wait_for_selector(".dot.ok", timeout=60000)
        page.click("#reset")
        page.wait_for_timeout(2500)
        for line in SCRIPT:
            say(page, line or QUIZ_ANSWER)
        page.wait_for_timeout(2000)
        context.close()
        browser.close()

    webm = next(raw.glob("*.webm"))
    import imageio_ffmpeg

    target = OUT / "demo_capture.mp4"
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-y", "-i", str(webm), "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-crf", "18", "-movflags", "+faststart", str(target)], check=True)
    print(f"Saved {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
