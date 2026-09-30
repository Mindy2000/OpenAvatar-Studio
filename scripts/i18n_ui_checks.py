"""Exercise English UI, language round-trips, draft preservation and content boundaries."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

HAN = re.compile(r"[\u3400-\u9fff]")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(args.base_url, wait_until="networkidle")
        page.evaluate("document.querySelectorAll('dialog[open]').forEach(node => node.close())")
        page.evaluate("async () => { await setInterfaceLanguage('en-US'); await openSettings(); }")

        def english(selector: str, *, allowed: tuple[str, ...] = ()) -> None:
            # Include hidden tabs, options, placeholders, tooltips and accessible labels.
            values = page.locator(selector).evaluate("""root => {
                const values = [], walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
                while (walker.nextNode()) {
                    const node = walker.currentNode;
                    if (!node.parentElement.closest('script,style,textarea')) values.push(node.nodeValue);
                }
                for (const node of root.querySelectorAll('[placeholder],[aria-label],[title],[alt]'))
                    for (const key of ['placeholder','aria-label','title','alt']) values.push(node.getAttribute(key) || '');
                return values;
            }""")
            leftovers = [value for value in values if HAN.search(value) and value.strip() not in allowed]
            assert not leftovers, (selector, leftovers)

        english("#settingsDialog")
        english("#wizardView")
        english("#onboardingDialog")
        english("#privacyDialog")
        page.evaluate("async () => { await openDiagnostics(); await openCapabilities(); }")
        english("#diagnosticsDialog")
        english("#capabilitiesDialog")
        page.evaluate("document.querySelectorAll('dialog[open]').forEach(node => node.close())")
        # Use the same Chinese text as a UI label to catch accidental whole-DOM translation.
        user_text = "声音样本"
        avatars = []
        for subject in ("self", "fictional"):
            response = page.request.post(f"{args.base_url}/api/avatars", data={
                "name": user_text, "purpose": "Locale regression", "relationship": "Friend",
                "subject_kind": subject, "consent_confirmed": True,
                "avatar_primary_language": "zh-CN", "world_region": "mainland_china",
            })
            assert response.status == 201, response.text()
            avatar_id = response.json()["id"]
            avatars.append(avatar_id)
            page.evaluate("""async id => {
                await openAvatar(id); await loadGuidedBuilder(); await loadTrainingJobs();
                await loadAvatarModelSettings(); await loadEvidence();
                await loadHistoryRecords(); await loadLifeArchive(); await loadVideoCallStatus();
                const checks = await api(`/api/avatars/${id}/checks`);
                renderEvaluation(checks, 'checks');
            }""", avatar_id)
            assert page.locator("#studioName").inner_text() == user_text
            english("#studioView", allowed=(user_text, "声"))
            english("#guidedBuilderPanel")
            page.evaluate("""() => {
                state.currentImport = { id: 'test', preview: {
                    import: {category:'chat'}, speakers:[{speaker:'声音样本',count:1}],
                    rows:[{id:1,speaker:'声音样本',content:'声音样本'}], total:1, truncated:false
                }};
                renderImportReview();
                renderPackagePreview({name:'声音样本',subject_kind:'fictional',version:3,file_count:1,asset_count:0,
                    persona_summary:'声音样本',warnings:['人物包缺少授权记录，导入后会以本次用户确认作为本地使用授权。']});
            }""")
            assert page.locator("#reviewRows span").inner_text() == user_text
            assert page.locator("#packagePreview b").first.inner_text() == user_text
            english("#packagePreview", allowed=(user_text,))
            # No HTML injection or translation of interpolated names.
            assert page.evaluate("""() => tr`已导入数字人：${'声音样本 <b>x</b>'}`""") == "Imported avatar: 声音样本 <b>x</b>"
            page.evaluate("async () => { await openSettings(); }")
            page.locator("#providerDisplayName").fill("未保存的连接名")
            page.locator("#providerApiKey").fill("dummy-not-a-real-key")
            page.locator('[data-provider-model="chat"]').fill("draft-model")
            page.locator('[data-provider-consent="audio"]').check()
            page.locator("#guidedAnswer").evaluate("node => { node.value = '我的未保存答案'; }")
            for locale in ("zh-CN", "en-US", "zh-CN", "en-US"):
                page.evaluate("language => setInterfaceLanguage(language)", locale)
                assert page.locator("html").get_attribute("lang") == locale
                assert page.locator("#providerDisplayName").input_value() == "未保存的连接名"
                assert page.locator("#providerApiKey").input_value() == "dummy-not-a-real-key"
                assert page.locator('[data-provider-model="chat"]').input_value() == "draft-model"
                assert page.locator('[data-provider-consent="audio"]').is_checked()
                assert page.locator("#guidedAnswer").input_value() == "我的未保存答案"
                assert page.locator("#reviewRows span").inner_text() == user_text
                assert page.locator("#studioName").inner_text() == user_text
                if locale == "zh-CN":
                    assert page.locator("#settingsDialog h2").inner_text() == "连接配置中心"
                else:
                    english("#settingsDialog")
                    english("#guidedBuilderPanel")
                    english("#studioView", allowed=(user_text, "声"))
            page.evaluate("document.querySelectorAll('dialog[open]').forEach(node => node.close())")
        # Real API error and template error retain dynamic values, but translate system text.
        error = page.evaluate("""async () => {
            try { await api('/api/avatars/does-not-exist'); } catch (error) { return error.message; }
        }""")
        assert error == "Avatar not found", error
        assert page.evaluate("systemText('模型连接测试失败（HTTP 503）')") == "Model connection test failed (HTTP 503)"
        assert page.evaluate("systemText('服务连接不存在：声音样本')") == "Service connection not found: 声音样本"
        assert page.evaluate("source => systemText(source)", "'未知 Builder 问题'") == "Unknown Builder question"
        assert page.evaluate("source => systemText(source)", "尚未配置 API Key；没有可用的视频服务") == "No API key configured; No available video service"
        # Remembered locale must work on a fresh page, with the avatar language unchanged.
        page.reload(wait_until="networkidle")
        assert page.locator("html").get_attribute("lang") == "en-US"
        assert page.request.get(f"{args.base_url}/api/avatars/{avatars[-1]}").json()["avatar_primary_language"] == "zh-CN"
        page.evaluate("async () => { await openSettings(); }")
        english("#settingsDialog")
        Path("output").mkdir(exist_ok=True)
        page.screenshot(path="output/english-settings.png", full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        page.locator('.settings-tabs').scroll_into_view_if_needed()
        assert page.locator('.settings-tabs').bounding_box()['height'] >= 44
        page.locator('[data-settings-tab="ocrSettingsPanel"]').click()
        assert page.locator('#ocrSettingsPanel').is_visible()
        english('#ocrSettingsPanel')
        page.locator('[data-settings-tab="providerHubPanel"]').click()
        page.screenshot(path="output/english-settings-mobile.png", full_page=True)
        english("#settingsDialog")
        page.evaluate("language => setInterfaceLanguage(language)", "zh-CN")
        assert not errors, errors
        browser.close()
    print("English UI, language switching, draft and content preservation checks passed.")


if __name__ == "__main__":
    main()
