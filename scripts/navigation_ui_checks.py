"""Exercise delayed navigation responses using disposable data, without AI calls."""
from __future__ import annotations

import argparse
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    args = parser.parse_args()
    base = args.base_url.rstrip('/')
    parsed = urlparse(base)
    if parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', 'localhost', '::1'} or parsed.port == 8877:
        parser.error('Use a disposable loopback server, never the primary desktop instance.')
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1200, 'height': 900})
        avatars, errors, external = [], [], []
        page.on('pageerror', lambda error: errors.append(str(error)))
        def local_only(route):
            target = urlparse(route.request.url)
            if target.scheme in {'http', 'https'} and target.netloc != parsed.netloc:
                external.append(route.request.url)
                route.abort()
            else:
                route.continue_()
        page.route('**/*', local_only)
        try:
            page.goto(base, wait_until='networkidle')
            page.evaluate("document.querySelectorAll('dialog[open]').forEach(d => d.close())")
            for name in ['导航人物甲', '导航人物乙']:
                response = page.request.post(base + '/api/avatars', data={'name': name, 'subject_kind': 'fictional', 'consent_confirmed': True})
                assert response.status == 201, response.text()
                avatars.append((response.json()['id'], name))
            first, second = [item[0] for item in avatars]
            pending = []
            first_url = f'{base}/api/avatars/{first}'
            first_response = page.request.get(first_url)
            def hold_first(route):
                pending.append(route)
            page.route(first_url, hold_first)
            # A slower first click must not overwrite the avatar opened by a later click.
            with page.expect_request(first_url):
                page.evaluate('id => { window.firstOpen = openAvatar(id); }', first)
            page.evaluate('id => openAvatar(id)', second)
            expect(page.locator('#studioName')).to_have_text('导航人物乙')
            assert pending
            pending.pop().fulfill(response=first_response)
            page.evaluate('window.firstOpen')
            expect(page.locator('#studioName')).to_have_text('导航人物乙')
            assert page.evaluate('state.current.id === state.currentId')
            page.unroute(first_url, hold_first)

            # Switching timelines while a previous request is in flight cannot render old rows.
            preview_url = f'{base}/api/avatars/{second}/messages?timeline_kind=preview'
            pending_preview = []
            page.route(preview_url, lambda route: pending_preview.append(route))
            with page.expect_request(preview_url):
                page.evaluate('() => { state.previewMode = true; window.oldMessages = loadMessages(); }')
            page.evaluate('async () => { state.previewMode = false; await loadMessages(); }')
            pending_preview.pop().fulfill(json=[{'id': 99999, 'role': 'user', 'content': '只属于预览的旧消息', 'channel': 'preview', 'message_kind': 'text'}])
            page.evaluate('window.oldMessages')
            expect(page.locator('#messageList')).not_to_contain_text('只属于预览的旧消息')
            page.unroute(preview_url)

            # Returning home while an avatar is loading must leave the home page visible.
            pending_home = []
            page.route(first_url, lambda route: pending_home.append(route))
            with page.expect_request(first_url):
                page.evaluate('id => { window.homeOpen = openAvatar(id); }', first)
            page.locator('[data-action="home"]:visible').first.click()
            expect(page.locator('#homeView')).to_be_visible()
            pending_home.pop().fulfill(response=first_response)
            page.evaluate('window.homeOpen')
            expect(page.locator('#homeView')).to_be_visible()
            assert not errors and not external, {'errors': errors, 'external': external}
        finally:
            page.unroute_all(behavior='ignoreErrors')
            for avatar_id, name in avatars:
                deleted = page.request.delete(f'{base}/api/avatars/{avatar_id}', params={'confirmation': name})
                assert deleted.ok, deleted.text()
            browser.close()
    print('Navigation passed: delayed avatar, timeline and home responses cannot overwrite the current screen; no cloud calls.')


if __name__ == '__main__':
    main()
