"""Exercise the public synthetic demo in an isolated phone-width Chromium."""
import re

from playwright.sync_api import expect, sync_playwright


BASE = "https://paper-trail-agent.vercel.app"


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        page = context.new_page()
        page.goto(BASE, wait_until="domcontentloaded")
        start = page.get_by_role("button", name="Start private demo session")
        expect(start).to_be_visible()
        case_url = None
        try:
            for _ in range(30):
                page.keyboard.press("Tab")
                if start.evaluate("(button) => button === document.activeElement"):
                    break
            expect(start).to_be_focused()
            page.keyboard.press("Enter")
            example = page.get_by_role("button", name="$50 wrong total")
            expect(example).to_be_visible()
            with page.expect_response(lambda response: response.url.endswith("/demo/cases/math_error")) as pending:
                example.tap()
            response = pending.value
            assert response.ok
            case_url = "/api/cases/" + response.json()["id"]
            expect(page.locator("#findings")).to_contain_text("50.00")
            assert page.evaluate("document.documentElement.scrollWidth === window.innerWidth")
            checklist = page.get_by_role("link", name="Export redacted checklist")
            expect(checklist).to_be_visible()
            assert checklist.bounding_box()["height"] >= 44
            export_url = checklist.get_attribute("href")
            assert export_url == case_url + "/export?format=md"
            exported = context.request.get(BASE + export_url)
            assert exported.ok
            assert re.search(r"50\.00\s+USD", exported.text())
            assert "DEMO-001" not in exported.text()
            print("Phone-width Chromium passed: keyboard start, touch case, layout width, and redacted checklist.")
        finally:
            token = next((cookie["value"] for cookie in context.cookies() if cookie["name"] == "pta_csrf"), None)
            if token:
                headers = {"X-CSRF-Token": token}
                if case_url:
                    assert context.request.delete(BASE + case_url, headers=headers).ok
                assert context.request.post(BASE + "/api/platform/auth/logout", headers=headers).ok


if __name__ == "__main__":
    main()
