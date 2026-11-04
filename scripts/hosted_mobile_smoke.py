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
            case_id = case_url.rsplit("/", 1)[1]
            page.locator("#history-query").fill("2026-10-31")
            page.locator("#history-status").select_option("discrepancies")
            page.get_by_role("button", name="Search cases").tap()
            history = page.get_by_role("region", name="Saved cases")
            reopen = history.get_by_role("button", name=f"Open {case_id[:8]}")
            expect(reopen).to_be_visible()
            with page.expect_response(lambda response: response.url.endswith(case_url)) as reopened:
                reopen.tap()
            assert reopened.value.ok
            expect(page.locator("#case-id")).to_have_text(case_id)

            page.get_by_role("checkbox", name="Compare two original statements side by side").check()
            primary = page.locator("#pdf")
            secondary = page.locator("#compare-pdf")
            for image in (primary, secondary):
                expect(image).to_be_visible()
            page.wait_for_function("""() => ['pdf', 'compare-pdf'].every(
                id => document.getElementById(id).naturalWidth > 0)""")
            assert primary.get_attribute("src") != secondary.get_attribute("src")
            assert primary.bounding_box()["y"] < secondary.bounding_box()["y"]
            assert page.evaluate("document.documentElement.scrollWidth === window.innerWidth")

            page.set_viewport_size({"width": 1280, "height": 900})
            assert primary.bounding_box()["x"] < secondary.bounding_box()["x"]
            assert abs(primary.bounding_box()["y"] - secondary.bounding_box()["y"]) < 2
            page.set_viewport_size({"width": 390, "height": 844})
            prepare = page.get_by_role("button", name="Prepare lender draft F1")
            expect(prepare).to_be_disabled()
            with page.expect_response(lambda response: response.request.method == "PATCH"
                                      and response.url.endswith(case_url + "/findings/F1")) as approved:
                page.get_by_role("button", name="Approve F1").tap()
            assert approved.value.ok
            expect(prepare).to_be_enabled()
            page.get_by_label("Draft purpose").select_option("statement_dispute")
            with page.expect_response(lambda response: "/findings/F1/draft?" in response.url) as prepared:
                prepare.tap()
            response = prepared.value
            assert response.ok
            draft = response.json()
            assert draft["difference"] == "50.00" and draft["delivery"] == "manual_only"
            assert draft["requires_final_human_review"] and draft["sent"] is False
            text = page.get_by_role("textbox", name="Lender draft for F1")
            expect(text).to_have_value(draft["text"])
            assert "3300.00 USD" in draft["text"] and "3350.00 USD" in draft["text"]
            assert "DEMO-001" not in draft["text"]
            page.get_by_role("button", name="Select draft text").tap()
            assert text.evaluate("(input) => input.selectionStart === 0 && input.selectionEnd === input.value.length")
            assert page.evaluate("document.documentElement.scrollWidth === window.innerWidth")
            print("Hosted Chromium passed keyboard, touch, exports, history, comparison and mobile dispute draft checks.")
        finally:
            token = next((cookie["value"] for cookie in context.cookies() if cookie["name"] == "pta_csrf"), None)
            if token:
                headers = {"X-CSRF-Token": token}
                if case_url:
                    assert context.request.delete(BASE + case_url, headers=headers).ok
                assert context.request.post(BASE + "/api/platform/auth/logout", headers=headers).ok


if __name__ == "__main__":
    main()
