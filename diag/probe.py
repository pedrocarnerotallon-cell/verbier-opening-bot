import json, re, asyncio
from playwright.async_api import async_playwright
URL = "https://verbier4vallees.ch/en/online-shop/activities/opening-session-st.nicholas-express_activity_426820"
async def main():
    reqs = []
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 1280, "height": 1600}, locale="en-GB")
        async def on_resp(r):
            u = r.url
            if r.request.resource_type in ("xhr", "fetch") or "api" in u.lower():
                body = ""
                try:
                    body = (await r.text())[:3000]
                except Exception:
                    pass
                reqs.append({"url": u, "method": r.request.method, "status": r.status, "post": r.request.post_data, "body": body})
        pg.on("response", on_resp)
        await pg.goto(URL, wait_until="networkidle", timeout=60000)
        await pg.screenshot(path="diag/1_page.png")
        for sel in ["text=/decline all/i", "text=/accept all/i"]:
            try:
                await pg.click(sel, timeout=2000); break
            except Exception:
                pass
        reqs.append({"marker": "---- CLICK BOOK NOW ----"})
        clicked = False
        await pg.wait_for_timeout(1500)
        els = pg.locator("text=/book now/i")
        n = await els.count()
        html_dump = []
        for i in range(n):
            try:
                html_dump.append(await els.nth(i).evaluate("e => (e.closest('a,button')||e).outerHTML.slice(0,800)"))
            except Exception as e:
                html_dump.append(str(e))
        open("diag/booknow_html.txt","w").write("\n\n".join(html_dump))
        for i in range(n):
            try:
                if await els.nth(i).is_visible():
                    await els.nth(i).click(timeout=5000); clicked = True; break
            except Exception as e:
                print("click fail", i, e)
        for sel in ([] if clicked else ["text=/book now/i"]):
            try:
                await pg.locator(sel).first.click(timeout=5000); clicked = True; break
            except Exception as e:
                print("click fail", sel, e)
        await pg.wait_for_timeout(8000)
        await pg.screenshot(path="diag/2_after_click.png", full_page=False)
        open("diag/after_click_text.txt", "w").write(await pg.inner_text("body"))
        frames = [f.url for f in pg.frames]
        out = {"clicked": clicked, "frames": frames, "page_url": pg.url}
        for f in pg.frames[1:]:
            try:
                out.setdefault("frame_texts", {})[f.url] = (await f.inner_text("body"))[:3000]
            except Exception as e:
                pass
        json.dump(out, open("diag/summary.json", "w"), indent=1)
        json.dump(reqs, open("diag/requests.json", "w"), indent=1)
        await b.close()
asyncio.run(main())
