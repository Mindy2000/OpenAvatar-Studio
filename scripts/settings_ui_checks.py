"""Exercise settings failures and restore-aware notification UI without providers."""
import argparse
from playwright.sync_api import sync_playwright, expect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    args = parser.parse_args()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width':1360, 'height':1000})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(args.base_url, wait_until='networkidle')
        if page.locator('#setupGuideDialog').is_visible():
            page.locator('#setupGuideDialog [data-setup-action="dismiss"]').last.click()

        def fail_optional(route):
            route.fulfill(status=500, json={'detail':'Isolated OCR configuration failure'})
        page.route('**/api/ocr-connections', fail_optional)
        page.locator('[data-action="open-settings"]').first.click()
        expect(page.locator('#settingsDialog')).to_be_visible()
        expect(page.locator('#providerDisplayName')).to_be_enabled()
        page.locator('[data-settings-tab="ocrSettingsPanel"]').click()
        expect(page.locator('#ocrSettingsPanel .settings-load-status')).to_contain_text('Isolated OCR')
        expect(page.locator('#ocrName')).to_be_disabled()
        page.unroute('**/api/ocr-connections', fail_optional)
        page.locator('#ocrSettingsPanel .settings-load-status button').click()
        expect(page.locator('#ocrName')).to_be_enabled()
        page.locator('[data-settings-tab="providerHubPanel"]').click()
        page.locator('#providerDisplayName').fill('Draft retained after Enter')
        page.locator('#providerDisplayName').press('Enter')
        expect(page.locator('#settingsDialog')).to_be_visible()
        expect(page.locator('#providerDisplayName')).to_have_value('Draft retained after Enter')
        page.locator('#settingsDialog .dialog-close').click()
        expect(page.locator('#settingsDialog')).not_to_be_visible()

        seen = []
        page.route('**/api/notifications/feed?**', lambda route: route.fulfill(json={
            'epoch':'restored-database', 'after_id':0,
            'items':[{'id':1,'title':'Restored notification','body':'Lower ID after recovery'}],
        }))
        def acknowledge(route):
            seen.append(route.request.url)
            route.fulfill(json={'read':True,'id':1})
        page.route('**/api/notifications/1/read?**', acknowledge)
        page.evaluate("state.lastNotificationId=51;state.notificationEpoch='old-database'")
        page.evaluate('async()=>{await pollNotifications()}')
        expect(page.locator('#toast')).to_contain_text('Restored notification')
        assert page.evaluate('state.lastNotificationId') == 1
        assert page.evaluate("localStorage.getItem('openavatar.notificationEpoch')") == 'restored-database'
        assert seen and 'epoch=restored-database' in seen[-1]
        assert not errors, errors
        browser.close()
    print('Settings partial-failure, Enter draft, and restored notification checks passed.')


if __name__ == '__main__':
    main()
