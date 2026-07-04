"""Playwright browser automation MCP Server."""
import os
from .base import BaseMCPServer


class PlaywrightServer(BaseMCPServer):
    def __init__(self, headless: bool = True, browser: str = "chromium", timeout: int = 30000):
        self.headless = headless
        self.browser_type = browser
        self.timeout = timeout
        self._page = None
        self._browser = None
        self._pw = None
        self._try_init()

    def _try_init(self):
        try:
            from playwright.sync_api import sync_playwright
            self._pw_cls = sync_playwright
        except ImportError:
            self._pw_cls = None

    def _get_page(self):
        if self._page:
            return self._page
        if not self._pw_cls:
            raise RuntimeError("playwright not installed — run: pip install playwright && playwright install chromium")
        self._pw = self._pw_cls().__enter__()
        br = getattr(self._pw, self.browser_type)
        self._browser = br.launch(headless=self.headless)
        self._page = self._browser.new_page()
        self._page.set_default_timeout(self.timeout)
        return self._page

    def navigate(self, url: str, wait_until: str = "load") -> dict:
        page = self._get_page()
        page.goto(url, wait_until=wait_until)
        return {"url": page.url, "title": page.title()}

    def get_text(self, selector: str = None) -> dict:
        page = self._get_page()
        if selector:
            text = page.locator(selector).inner_text()
        else:
            text = page.inner_text("body")
        return {"text": text[:5000]}

    def get_html(self, selector: str = None) -> dict:
        page = self._get_page()
        html = page.locator(selector).inner_html() if selector else page.content()
        return {"html": html[:10000]}

    def click(self, selector: str) -> dict:
        self._get_page().click(selector)
        return {"clicked": selector}

    def fill(self, selector: str, value: str) -> dict:
        self._get_page().fill(selector, value)
        return {"filled": selector}

    def screenshot(self, path: str = None, full_page: bool = False) -> dict:
        out = path or "screenshot.png"
        self._get_page().screenshot(path=out, full_page=full_page)
        return {"path": out}

    def evaluate(self, script: str) -> dict:
        result = self._get_page().evaluate(script)
        return {"result": result}

    def wait_for(self, selector: str = None, url: str = None, state: str = "visible") -> dict:
        page = self._get_page()
        if selector:
            page.wait_for_selector(selector, state=state)
        elif url:
            page.wait_for_url(url)
        return {"done": True}

    def close_browser(self) -> dict:
        if self._browser:
            self._browser.close()
            self._browser = self._page = None
        return {"closed": True}
