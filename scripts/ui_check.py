"""Drive the web UI in a real browser and save screenshots to artifacts/.

    python scripts/ui_check.py     (needs: pip install playwright; uses installed Chrome)
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / "artifacts"
OUT.mkdir(exist_ok=True)
BASE = "http://127.0.0.1:8000"
errors = []


def answers(page):
    return page.locator(".turn.answer").count()


def ask(page, text=None, chip=None, timeout=90000):
    before = answers(page)
    if chip is not None:
        page.locator(".chip").nth(chip).click()
    else:
        page.fill("#text", text)
        page.press("#text", "Enter")
    page.wait_for_function(f"document.querySelectorAll('.turn.answer').length > {before}", timeout=timeout)
    page.wait_for_timeout(400)


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome")
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE)
    page.wait_for_selector(".dot.ok", timeout=30000)
    page.screenshot(path=str(OUT / "ui_1_welcome.png"))

    ask(page, chip=0)                       # skew lines
    page.screenshot(path=str(OUT / "ui_2_excluded.png"))
    ask(page, "Quiz me on H2 Computing")
    page.screenshot(path=str(OUT / "ui_3_quiz.png"))
    ask(page, "I don't remember, sorry")
    ask(page, "What should I revise first?")
    page.wait_for_timeout(800)
    page.screenshot(path=str(OUT / "ui_4_revision.png"))

    mobile = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2)
    mobile.goto(BASE)
    mobile.wait_for_selector(".dot.ok", timeout=30000)
    ask(mobile, "Is hypothesis testing on the H2 Maths exam?")
    mobile.screenshot(path=str(OUT / "ui_5_mobile.png"), full_page=False)
    width = mobile.evaluate("document.documentElement.scrollWidth")
    for pg in (page, mobile):
        errors += [f"answer error: {t}" for t in pg.locator(".turn.answer.error .say").all_inner_texts()]
    browser.close()

print("console errors:", errors or "none")
print("mobile scrollWidth:", width, "(should be 390)")
sys.exit(1 if errors or width > 390 else 0)
