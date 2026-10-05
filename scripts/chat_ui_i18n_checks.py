"""Check chat translations using disposable local data, without model/device calls."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


HAN = re.compile(r"[\u3400-\u9fff]")
PANELS = (
    "#chatTab", "#callChoiceDialog", "#voiceCallDialog", "#chatCameraDialog",
    "#chatAttachmentDialog", "#chatLocationDialog", "#chatFavoritesDialog",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("--base-url must point to the runner's disposable loopback server")
    args.output.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        avatar_id = None
        original_locale = "zh-CN"
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors: list[str] = []
        external_requests: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def local_only(route) -> None:
            target = urlparse(route.request.url)
            if target.scheme in {"http", "https"} and target.netloc != parsed.netloc:
                external_requests.append(route.request.url)
                route.abort()
            else:
                route.continue_()

        page.route("**/*", local_only)
        try:
            page.goto(base, wait_until="networkidle")
            original_locale = page.locator("html").get_attribute("lang") or "zh-CN"
            assert page.locator("#chatAvatar").inner_text() == "O"
            assert page.locator("#voicePersonInitial").inner_text() == "O"
            assert page.locator("#voicePersonName").inner_text() == page.evaluate("tr('数字人')")
            created = page.request.post(f"{base}/api/avatars", data={
                "name": "中文姓名", "subject_kind": "self", "adult_subject": True,
                "consent_confirmed": True,
            })
            assert created.status == 201, created.text()
            avatar_id = created.json()["id"]
            page.evaluate("""id => {
                document.querySelectorAll('dialog[open]').forEach(node => node.close());
                return openAvatar(id);
            }""", avatar_id)
            page.wait_for_load_state("networkidle")
            page.evaluate("async () => { await setInterfaceLanguage('en-US'); }")
            page.evaluate("async () => { await openVoiceWindow(); }")

            remaining = {}
            for selector in PANELS:
                values = page.locator(selector).evaluate("""root => {
                    const values = [], walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
                    while (walker.nextNode()) values.push(walker.currentNode.nodeValue);
                    for (const node of root.querySelectorAll('[aria-label],[title],[placeholder],[alt]'))
                        for (const attr of ['aria-label', 'title', 'placeholder', 'alt'])
                            values.push(node.getAttribute(attr) || '');
                    return values;
                }""")
                remaining[selector] = [
                    value for value in values
                    if HAN.search(value) and value.strip() not in {"中文姓名", "中"}
                ]
            assert not any(remaining.values()), remaining
            page.screenshot(path=str(args.output / "chat-call-english.png"))

            # Exercise component output without storing messages or invoking a model.
            rendered = page.evaluate("""() => ['image', 'audio', 'file', 'location', 'call'].map(kind =>
                renderChatMessage({id: 1, role: 'user', content: '中文原文', message_kind: kind,
                    media_url: `/api/avatars/${state.currentId}/messages/1/file`,
                    attachment: {name: '中文文件', address: '中文地点', duration: 12}})).join('')
            """)
            assert all(value in rendered for value in ("中文原文", "中文文件", "中文地点"))
            stripped = rendered.replace("中文原文", "").replace("中文文件", "").replace("中文地点", "")
            assert not HAN.search(stripped), stripped
            # No socket is created and start() is never called: this checks only labels.
            statuses = page.evaluate("""() => {
                const output = [];
                const controller = new VoiceCallController({avatarId: state.currentId,
                    status: value => output.push(value), transcript: () => {}, changed: () => {}});
                controller.active = true; controller.ready = true;
                controller.submit('原始文字'); controller.end();
                return output;
            }""")
            assert statuses and not any(HAN.search(value) for value in statuses), statuses
            page.evaluate("() => { endVoiceCall(); $('#toggleVoiceMessage').click(); }")
            assert page.locator("#holdVoiceMessage").inner_text() == "Hold to talk"
            page.evaluate("async () => { await setInterfaceLanguage('zh-CN'); }")
            assert page.locator("#holdVoiceMessage").inner_text() == "按住说话"
            assert page.locator("#chatPersonName").inner_text() == "中文姓名"
            page.evaluate("async () => { await setInterfaceLanguage('en-US'); }")
            assert page.locator("#holdVoiceMessage").inner_text() == "Hold to talk"
            page.evaluate("() => { $('#toggleChatMore').click(); }")
            page.set_viewport_size({"width": 390, "height": 844})
            page.screenshot(path=str(args.output / "chat-composer-english-mobile.png"))
            assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
            assert not errors, errors
            assert not external_requests, external_requests
            result = {
                "panels_checked": len(PANELS), "remaining_chinese_ui": remaining,
                "user_content_preserved": True, "language_roundtrip": True,
                "dynamic_call_statuses": statuses, "mobile_no_horizontal_overflow": True,
                "page_errors": errors, "external_requests": external_requests, "cloud_calls": 0,
                "generic_placeholders": True,
            }
            (args.output / "chat-ui-i18n.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8",
            )
            print(json.dumps(result, ensure_ascii=False))
        finally:
            try:
                try:
                    page.evaluate("language => setInterfaceLanguage(language)", original_locale)
                finally:
                    if avatar_id:
                        deleted = page.request.delete(
                            f"{base}/api/avatars/{avatar_id}", params={"confirmation": "中文姓名"},
                        )
                        assert deleted.ok, deleted.text()
            finally:
                browser.close()


if __name__ == "__main__":
    main()
