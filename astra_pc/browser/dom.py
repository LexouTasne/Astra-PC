from __future__ import annotations


class BrowserDOM:
    """Connects to a Chromium CDP endpoint when available; otherwise stays disabled."""

    def __init__(self, endpoint: str = "http://127.0.0.1:9222"):
        self.endpoint = endpoint

    def snapshot(self, limit: int = 80) -> list[dict]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return []

        try:
            with sync_playwright() as p:
                browser = p.chromium.connect_over_cdp(self.endpoint)
                if not browser.contexts or not browser.contexts[0].pages:
                    browser.close()
                    return []
                page = browser.contexts[0].pages[-1]
                nodes = page.locator("a,button,input,textarea,select,[role]").all()
                out = []
                for node in nodes[:limit]:
                    try:
                        out.append(
                            {
                                "tag": node.evaluate("(e)=>e.tagName"),
                                "text": node.inner_text(timeout=80)[:200],
                                "aria": node.get_attribute("aria-label"),
                                "role": node.get_attribute("role"),
                            }
                        )
                    except Exception:
                        continue
                browser.close()
                return out
        except Exception:
            return []
