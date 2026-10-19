"""Rendered homepage fetch with headless Chromium (spec §8.2). Only for domains whose
robots.txt allows "/" for our UA (decided at T2 and recorded in the T2 fetch log)."""

from __future__ import annotations

import asyncio
import sys

from mcs.fetch.store import FetchLog, FetchRecord, save_body

BLOCK_TYPES = {"image", "media", "font"}  # like blockResources; scripts must run (pixel)


async def render_domains(targets: list[tuple[str, str]], user_agent: str, wait_ms: int = 3000,
                         concurrency: int = 6, timeout_ms: int = 30000) -> dict:
    from playwright.async_api import async_playwright

    log = FetchLog("RENDER")
    done = {r["domain"] for r in log.read()}
    targets = [t for t in targets if t[0] not in done]
    sem = asyncio.Semaphore(concurrency)
    ok = 0
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--disable-dev-shm-usage"])

        async def one(domain: str, url: str):
            nonlocal ok
            async with sem:
                ctx = await browser.new_context(user_agent=user_agent, java_script_enabled=True)
                page = await ctx.new_page()

                async def route(r):
                    if r.request.resource_type in BLOCK_TYPES:
                        await r.abort()
                    else:
                        await r.continue_()

                await page.route("**/*", route)
                rec = FetchRecord(domain=domain, host=url.split("/")[2], snapshot="RENDER",
                                  resource="homepage_rendered", source="live_playwright",
                                  requested_url=url)
                try:
                    resp = await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                    await page.wait_for_timeout(wait_ms)
                    html = (await page.content()).encode("utf-8")
                    rec.http_status = resp.status if resp else None
                    rec.final_url = page.url
                    rec.fetch_status = "OK" if resp and resp.ok else f"HTTP_{rec.http_status}"
                    rec.bytes = len(html)
                    rec.sha256, rec.body_path = save_body(html, "homepage")
                    from mcs.fetch.challenge import is_challenge
                    rec.challenge_detected = is_challenge(html)
                    ok += 1
                except Exception as e:  # noqa: BLE001
                    rec.fetch_status = "NETWORK_ERROR"
                    rec.error = f"{type(e).__name__}: {e}"[:300]
                finally:
                    await ctx.close()
                log.append(rec)

        await asyncio.gather(*(one(d, u) for d, u in targets))
        await browser.close()
    print(f"[render] {ok}/{len(targets)} rendered", file=sys.stderr)
    return {"targets": len(targets), "ok": ok}
