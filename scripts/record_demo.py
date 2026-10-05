"""Record a clean screen capture of the real app running the demo script.

    python run.py                      # in another terminal, with your chosen brain
    python scripts/record_demo.py      # needs: pip install playwright imageio-ffmpeg

Saves artifacts/demo_capture.mp4 (silent: add your voice-over, see docs/DEMO_SCRIPT.md).
Questions are typed at dictation speed so viewers can read them, and the time
spent waiting on the model is cut down to a short "Thinking..." beat, so the
video shows the product rather than the rate limit.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "artifacts"
SIZE = {"width": 1600, "height": 900}
# Follows docs/DEMO_SCRIPT.md.
SCRIPT = [
    "Is the ratio test on the AP Calculus AB exam?",
    "What about BC?",
    "Do I need the epsilon-delta definition of a limit for AP Calc?",
    "Is Big-O notation on AP Computer Science Principles?",
    "Are circles on the PSAT 8/9?",
    "I'm taking AP Calc BC and the SAT, my exam is May 11",
    "Quiz me",
    None,  # answer the quiz (filled in below)
    "What should I revise first?",
]
QUIZ_ANSWER = "I'm not sure, can you tell me?"


KEEP_THINKING = 1.5   # seconds of "Thinking..." kept after each question
# Groq's free tier allows about two turns a minute: pause between questions, then cut the pause out.
PACE = 30
WAITS: list[tuple[float, float]] = []   # spans to cut, seconds since recording began
START = 0.0


def say(page, text: str, first: bool = False) -> None:
    if not first:
        paused = time.monotonic() - START
        page.wait_for_timeout(PACE * 1000)
        WAITS.append((paused - KEEP_THINKING - 0.3, time.monotonic() - START))  # cut the whole pause
    before = page.locator(".turn.answer").count()
    page.click("#text")
    page.keyboard.type(text, delay=45)
    page.wait_for_timeout(400)
    page.keyboard.press("Enter")
    sent = time.monotonic() - START
    page.wait_for_function(f"document.querySelectorAll('.turn.answer').length > {before}", timeout=180000)
    WAITS.append((sent, time.monotonic() - START))
    page.wait_for_timeout(4500)  # let viewers read the answer and card


def main() -> int:
    OUT.mkdir(exist_ok=True)
    raw = OUT / "raw_video"
    shutil.rmtree(raw, ignore_errors=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        context = browser.new_context(viewport=SIZE, record_video_dir=str(raw), record_video_size=SIZE)
        page = context.new_page()
        global START
        START = time.monotonic()
        page.goto("http://127.0.0.1:8000")
        # A fresh student, so the revision list and countdown show only this run.
        page.evaluate("localStorage.setItem('syllabuddy.student', 'stu-demo-' + Date.now())")
        page.reload()
        page.wait_for_selector(".dot.ok", timeout=60000)
        page.click("#reset")
        page.wait_for_timeout(2500)
        for i, line in enumerate(SCRIPT):
            say(page, line or QUIZ_ANSWER, first=(i == 0))
        page.wait_for_timeout(2000)
        context.close()
        browser.close()

    webm = next(raw.glob("*.webm"))
    import imageio_ffmpeg

    # Keep everything except the long middle of each wait.
    cuts = [(sent + KEEP_THINKING, answered - 0.3) for sent, answered in WAITS if answered - sent > KEEP_THINKING + 0.6]
    keep = "+".join(f"between(t,{a:.2f},{b:.2f})" for a, b in cuts)
    # Browser recordings are variable frame rate, so normalise to 25 fps before cutting.
    select = f"fps=25,select='not({keep})',setpts=N/25/TB" if cuts else "fps=25"
    target = OUT / "demo_capture.mp4"
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-y", "-i", str(webm), "-vf", select,
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-r", "25", "-movflags", "+faststart",
                    str(target)], check=True)
    removed = sum(b - a for a, b in cuts)
    print(f"Saved {target} (cut {removed:.0f}s of waiting across {len(cuts)} answers)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
