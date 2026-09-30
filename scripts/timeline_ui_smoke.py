#!/usr/bin/env python3
from __future__ import annotations

import os
import re
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main() -> None:
    base_url = os.environ.get("OPENAVATAR_TEST_URL", "http://127.0.0.1:8767")
    chrome = os.environ.get("PLAYWRIGHT_CHROME_PATH") or None
    screenshot_dir = Path(os.environ.get("OPENAVATAR_SCREENSHOT_DIR", "output/timeline-ui"))
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=chrome)
        print("browser ready", flush=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("console", lambda event: errors.append(event.text) if event.type == "error" else None)
        page.on("pageerror", lambda error: errors.append(str(error)))
        created = page.request.post(f"{base_url}/api/avatars", data={
            "name": "Timeline test", "subject_kind": "fictional", "consent_confirmed": True,
        })
        assert created.ok, created.text()
        avatar_id = created.json()["id"]
        imported = page.request.post(f"{base_url}/api/avatars/{avatar_id}/imports?category=conversation", data='[{"speaker":"test","content":"history fixture"}]', headers={
            "Content-Type": "application/json", "X-File-Name": "history.json",
        })
        assert imported.ok, imported.text()
        confirmed = page.request.post(f"{base_url}/api/avatars/{avatar_id}/imports/{imported.json()['id']}/confirm", data={"avatar_speakers": ["test"]})
        assert confirmed.ok, confirmed.text()
        print("fixture ready", flush=True)

        page.goto(base_url, wait_until="networkidle")
        print("page ready", flush=True)
        page.evaluate("id => { const dialog = document.querySelector('#onboardingDialog'); if (dialog?.open) dialog.close(); return openAvatar(id); }", avatar_id)
        print("avatar clicked", flush=True)
        page.wait_for_selector("#studioView:not(.hidden)")
        print("studio ready", flush=True)
        page.get_by_role("button", name="聊天记录", exact=True).click()
        print("history clicked", flush=True)
        page.wait_for_selector("#historyTab:not(.hidden) .timeline-record")
        assert int(page.locator("#historyTab .timeline-record").count()) >= 1
        page.screenshot(path=str(screenshot_dir / "history-desktop.png"), full_page=True)

        page.get_by_role("button", name="人生档案", exact=True).click()
        page.wait_for_selector("#timelineTab:not(.hidden)")
        expect(page.locator("#timelineHistoricalCount")).not_to_have_text("0")
        # A fresh avatar has imported history, but no fabricated runtime conversations.
        assert page.locator("#activeTimelineRecords .timeline-record").count() == 0
        page.locator('[data-timeline-kind="preview"]').click()
        expect(page.locator('[data-timeline-kind="preview"]')).to_have_class(re.compile("active"))
        page.wait_for_timeout(300)
        rule_text = page.locator("#timelineRuleNote").inner_text().lower()
        assert "测试" in rule_text or "test" in rule_text
        page.screenshot(path=str(screenshot_dir / "archive-desktop.png"), full_page=True)

        mobile = browser.new_page(viewport={"width": 390, "height": 844})
        mobile.goto(base_url, wait_until="networkidle")
        mobile.evaluate("id => { const dialog = document.querySelector('#onboardingDialog'); if (dialog?.open) dialog.close(); return openAvatar(id); }", avatar_id)
        mobile.get_by_role("button", name="人生档案", exact=True).click()
        mobile.wait_for_selector("#timelineTab:not(.hidden)")
        assert mobile.locator("#timelineTab h2").is_visible()
        mobile.screenshot(path=str(screenshot_dir / "archive-mobile.png"), full_page=True)
        mobile.close()
        browser.close()
    assert not errors, errors
    print("timeline UI smoke passed")


if __name__ == "__main__":
    main()
