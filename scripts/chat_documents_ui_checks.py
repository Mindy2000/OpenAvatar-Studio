"""Check explicit document UI with a local HTTP substitute; never call a model."""
from __future__ import annotations

import argparse
import json
from urllib.parse import quote, urlparse

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    args = parser.parse_args()
    base = args.base_url.rstrip('/')
    parsed = urlparse(base)
    if parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', 'localhost', '::1'} or parsed.port == 8877:
        parser.error('Use a disposable loopback test server, never the primary desktop instance.')
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1100, 'height': 900})
        calls, external, errors = [], [], []
        avatar = None
        original_locale = 'zh-CN'
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
            original_locale = page.locator('html').get_attribute('lang')
            created = page.request.post(base + '/api/avatars', data={'name': '文档检查', 'subject_kind': 'fictional', 'adult_subject': True, 'consent_confirmed': True})
            assert created.status == 201, created.text()
            avatar = created.json()['id']
            uploaded = page.request.post(f'{base}/api/avatars/{avatar}/messages/attachment?kind=file&preview_mode=true&client_key=document-ui',
                                         data=b'Library opens at 9 AM.', headers={'X-File-Name': quote('时刻表.txt'), 'Content-Type': 'text/plain'})
            assert uploaded.status == 201, uploaded.text()
            message_id = uploaded.json()['id']
            page.evaluate("async id => { document.querySelectorAll('dialog[open]').forEach(d=>d.close()); await openAvatar(id); }", avatar)
            page.locator('[data-tab="chat"]').click()
            # Readiness chooses preview for this incomplete disposable avatar.
            assert page.evaluate('!!state.previewMode')
            page.locator(f'[data-read-document="{message_id}"]').click()
            expect(page.locator('#chatDocumentDialog')).to_be_visible()
            expect(page.locator('#sendChatDocument')).to_be_enabled()
            assert calls == []
            page.locator('#chatDocumentQuestion').fill('图书馆几点开？')
            page.locator('#chatDocumentConsent').check()
            page.evaluate("async () => { await setInterfaceLanguage('en-US'); }")
            expect(page.locator('#chatDocumentQuestion')).to_have_value('图书馆几点开？')
            expect(page.locator('#chatDocumentConsent')).to_be_checked()
            expect(page.locator('#sendChatDocument')).to_have_text('Confirm and ask')
            expect(page.locator('#chatDocumentScope')).to_contain_text('ordinary chat does not automatically include it')
            assert '可能产生费用' not in page.locator('#chatDocumentConsentLabel').inner_text()

            def fake_read(route):
                payload = route.request.post_data_json
                calls.append(payload)
                assert payload['confirm_billable_call'] and payload['preview_mode']
                if len(calls) == 1:
                    route.fulfill(status=200, content_type='application/json', body=json.dumps({
                        'reply': '图书馆上午九点开门。', 'cached': False,
                        'source': {'name': '时刻表.txt', 'message_id': message_id, 'characters': 24, 'pages': None, 'empty_pages': []}
                    }))
                else:
                    route.fulfill(status=502, content_type='application/json', body=json.dumps({'detail': {'code': 'document_provider_failed', 'message': '文件提问未完成，未自动重试或切换服务。请检查连接后重新点击确认。'}}))
            page.route(f'**/api/avatars/{avatar}/messages/{message_id}/document/read', fake_read)
            page.locator('#sendChatDocument').click()
            expect(page.locator('#chatDocumentResult')).to_contain_text('图书馆上午九点开门。')
            expect(page.locator('#chatDocumentResult')).to_contain_text('File source: 时刻表.txt')
            expect(page.locator('#chatDocumentConsent')).not_to_be_checked()
            assert len(calls) == 1
            page.evaluate("async () => { await setInterfaceLanguage('zh-CN'); }")
            expect(page.locator('#chatDocumentResult')).to_contain_text('文件来源：时刻表.txt')
            page.locator('#chatDocumentQuestion').fill('周末呢？')
            page.locator('#chatDocumentConsent').check()
            page.locator('#sendChatDocument').click()
            expect(page.locator('#chatDocumentError')).to_contain_text('未自动重试')
            page.evaluate("async () => { await setInterfaceLanguage('en-US'); }")
            expect(page.locator('#chatDocumentError')).to_contain_text('No retry or provider switch')
            expect(page.locator('#chatDocumentQuestion')).to_have_value('周末呢？')
            assert len(calls) == 2 and calls[0]['request_id'] != calls[1]['request_id']
            page.set_viewport_size({'width': 390, 'height': 844})
            assert page.locator('#chatDocumentDialog').evaluate('d => d.scrollWidth <= d.clientWidth + 1')
            assert not errors and not external, {'errors': errors, 'external': external}
        finally:
            try:
                try:
                    page.evaluate('locale => setInterfaceLanguage(locale)', original_locale)
                finally:
                    if avatar:
                        deleted = page.request.delete(f'{base}/api/avatars/{avatar}', params={'confirmation': '文档检查'})
                        assert deleted.ok, deleted.text()
            finally:
                browser.close()
    print('Document UI passed: explicit consent, local-only HTTP substitute, source/follow-up, language/draft/result preservation, no automatic retry, mobile width; test data cleaned.')


if __name__ == '__main__':
    main()
