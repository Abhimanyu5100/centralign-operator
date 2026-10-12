"""README images from replayed runs (`make readme-assets`): no API key, no LLM quota, deterministic.

Replays T1 (its passing flaky_500 run), T6, T4 and T5 into a clean run store (runs/readme.db), serves the run viewer and approval inbox on it,
replays T9 with a person's decision pending, and records that person approving it in the inbox. Writes 2x PNGs and
an optimised GIF (no watermark, no labels) to docs/assets/. Harness side only: agent/ never imports this."""

import asyncio
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import httpx
from PIL import Image
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "runs" / "readme.db"
OUT = ROOT / "docs" / "assets"
PORT = 8101  # not make ui's 8100, so a running inbox is never disturbed
BASE = f"http://127.0.0.1:{PORT}"
SHOTS = {"T1": "t1", "T6": "t6", "T4": "t4", "T5": "t5"}
EXTRA = {"T1": ("--chaos", "flaky_500")}  # T1 passed live only under chaos in the headline run; this replay shows it


def replay(task: str, *extra: str, wait: bool = True) -> subprocess.Popen:
    proc = subprocess.Popen([sys.executable, "-m", "bench.run_agent", task, "--replay", "--store", str(STORE), *extra],
                            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    if wait:
        proc.wait()
    return proc


def run_id(request_start: str) -> str:
    with sqlite3.connect(STORE) as db:
        return db.execute("SELECT run_id FROM runs WHERE request LIKE ? ORDER BY rowid DESC",
                          (request_start + "%",)).fetchone()[0]


async def rows_clip(page, first: int, last: int) -> dict:
    return await page.evaluate("""([a, b]) => {
        const rows = [...document.querySelectorAll('tr')], t = rows[a].closest('table').getBoundingClientRect();
        const r1 = rows[a].getBoundingClientRect(), r2 = rows[b].getBoundingClientRect();
        return {x: t.left, y: r1.top + window.scrollY, width: t.width, height: r2.bottom - r1.top}; }""", [first, last])


async def screenshots(browser) -> None:
    page = await browser.new_page(viewport={"width": 1100, "height": 900}, device_scale_factor=2)
    await page.goto(f"{BASE}/runs")
    await page.locator("table").screenshot(path=OUT / "runs.png")
    for task, name in SHOTS.items():
        request = {"T1": "Process the latest", "T6": "Process the new", "T4": "Pay the pending",
                   "T5": "Pay the invoice from Kapoor"}[task]
        await page.goto(f"{BASE}/runs/{run_id(request)}")
        await page.locator("pre").last.screenshot(path=OUT / f"{name}-report.png")
        if task == "T1":  # the plan, the first write and its policy decision
            rows = await page.evaluate("""() => [...document.querySelectorAll('tr')].map(r =>
                [(r.cells[1] || {}).textContent || '', (r.cells[2] || {}).textContent || ''])""")
            first = next(i for i, (kind, _) in enumerate(rows) if kind.strip() == "plan")
            write = next(i for i, (kind, what) in enumerate(rows) if kind.strip() == "tool_call" and "submit_invoice" in what)
            await page.screenshot(path=OUT / "t1-timeline.png", full_page=True,
                                  clip=await rows_clip(page, first, min(write + 8, len(rows) - 1)))
    await page.close()


async def approval_gif(browser) -> None:
    held = replay("T9:approve", "--approve-wait", "300", wait=False)
    page = await browser.new_page(viewport={"width": 1100, "height": 760})
    frames: list[tuple[Image.Image, int]] = []

    async def snap(ms: int) -> None:
        path = OUT / ".frame.png"
        await page.screenshot(path=path)
        frames.append((Image.open(path).convert("RGB"), ms))

    for _ in range(120):  # until the held send reaches the inbox
        await page.goto(BASE + "/")
        if await page.locator("button", has_text="Approve").count():
            break
        await asyncio.sleep(1)
    else:
        raise SystemExit("T9 never reached the inbox")
    await page.locator("section.card").first.screenshot(path=OUT / "inbox-card.png")
    await snap(2800)
    await page.get_by_label("Your name").fill("Finance reviewer")
    await snap(900)
    await page.locator("button", has_text="Approve").first.click()
    await page.wait_for_load_state()
    await snap(1800)
    held.wait(timeout=300)
    await page.goto(f"{BASE}/runs/{run_id('Email Sharma')}")
    await snap(2600)
    await page.locator("pre").last.scroll_into_view_if_needed()
    await snap(3600)
    (OUT / ".frame.png").unlink()
    small = [im.resize((880, 608), Image.LANCZOS).quantize(colors=128, method=Image.Quantize.MEDIANCUT,
                                                         dither=Image.Dither.NONE) for im, _ in frames]
    small[0].save(OUT / "t9-approve.gif", save_all=True, append_images=small[1:], loop=0, optimize=True,
                  duration=[ms for _, ms in frames])
    await page.close()


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    STORE.unlink(missing_ok=True)
    for task in SHOTS:
        replay(task, *EXTRA.get(task, ()))
    ui = subprocess.Popen([sys.executable, "-m", "uvicorn", "--factory", "ui.app:create_app", "--host", "127.0.0.1",
                           "--port", str(PORT)], cwd=ROOT, env={**os.environ, "RUN_STORE": str(STORE)},
                          stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    try:
        for _ in range(50):
            try:
                httpx.get(BASE + "/runs", timeout=1)
                break
            except httpx.HTTPError:
                time.sleep(0.2)
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            await screenshots(browser)
            await approval_gif(browser)
            await browser.close()
    finally:
        ui.terminate()
        ui.wait()
    for path in sorted(OUT.iterdir()):
        print(f"{path.relative_to(ROOT)}  {path.stat().st_size // 1024} KB")


if __name__ == "__main__":
    asyncio.run(main())
