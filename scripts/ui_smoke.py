from __future__ import annotations

import argparse
import json
import os
import struct
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


class FakeModelHandler(BaseHTTPRequestHandler):
    requests: list[dict] = []
    def log_message(self, *_args) -> None:
        return

    def do_GET(self) -> None:
        body = json.dumps({"data": [{"id": "local-test-model"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        self.requests.append(payload)
        json_mode = payload.get("response_format", {}).get("type") == "json_object"
        content = json.dumps({
            "summary": "小满是一个表达自然、重视边界并保留真实资料依据的数字人。",
            "traits": ["自然", "克制"],
            "speaking_style": "使用简短、自然的即时聊天表达。",
            "boundaries": "不编造未在资料中出现的经历。",
        }, ensure_ascii=False) if json_mode else "你好，我会依据已经确认的资料回答。"
        if not json_mode and payload.get("messages"):
            try:
                selected_file = json.loads(payload["messages"][-1]["content"])
            except (ValueError, TypeError):
                selected_file = {}
            if isinstance(selected_file, dict) and selected_file.get("document"):
                content = "文件写明：集合时间是周六上午九点，地点是图书馆。"
        if payload.get("stream"):
            chunks = [content[: max(1, len(content) // 2)], content[max(1, len(content) // 2):]]
            body = "".join(
                f"data: {json.dumps({'choices': [{'delta': {'content': chunk}}]}, ensure_ascii=False)}\n\n"
                for chunk in chunks if chunk
            ) + "data: [DONE]\n\n"
            encoded = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
            return
        body = json.dumps({"choices": [{"message": {"content": content}}]}, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def silent_wav() -> bytes:
    samples = b"\x00\x00" * 8000
    return b"RIFF" + struct.pack("<I", 36 + len(samples)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, 8000, 16000, 2, 16) + b"data" + struct.pack("<I", len(samples)) + samples


def main() -> int:
    parser = argparse.ArgumentParser(description="Run OpenAvatar Studio browser release smoke tests.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8767")
    args = parser.parse_args()
    output = Path(os.environ.get("OPENAVATAR_SCREENSHOT_DIR", "output"))
    output.mkdir(parents=True, exist_ok=True)
    model_server = ThreadingHTTPServer(("127.0.0.1", 0), FakeModelHandler)
    threading.Thread(target=model_server.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            chat_file = folder / "chat.json"
            audio_file = folder / "voice.wav"
            fictional_file = folder / "avatar.md"
            document_file = folder / "校园活动.txt"
            document_file.write_text("集合时间：周六上午九点。集合地点：图书馆。请带水杯。", encoding="utf-8")
            chat_file.write_text(json.dumps({"messages": [{"speaker": "小满", "content": "哈哈，今天想散散步"}]}, ensure_ascii=False), encoding="utf-8")
            audio_file.write_bytes(silent_wav())
            fictional_file.write_text("""# 林澄
## 身份
- 林澄是原创虚构人物，在北美经营一间社区唱片店。
## 核心性格
- 好奇、坦率、有边界感。
## 说话风格
- 使用自然英文短句，也能理解中文。
## 世界模型
- 地点、社会规则、日历和事件按照北美场景运行。
## 不变规则
- 不冒充真实人物，不编造未批准的过去经历。
""", encoding="utf-8")

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                console_errors: list[str] = []
                page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
                page.goto(args.base_url)
                page.wait_for_load_state("networkidle")
                if page.locator("#onboardingDialog[open]").count():
                    page.locator("[data-action='complete-onboarding']").click()
                if page.locator("#setupGuideDialog[open]").count():
                    page.locator("#setupGuideDialog [data-setup-action='dismiss']").last.click()

                # The guide navigates to the real settings screen and returns
                # without saving a connection or initiating a provider test.
                before_guide = len(FakeModelHandler.requests)
                page.locator("[data-action='open-onboarding']").first.click()
                page.locator("#setupGuideDialog [data-setup-action='configure'][data-capability='chat']").click()
                expect(page.locator("#settingsDialog")).to_be_visible()
                page.locator("#settingsDialog .dialog-close").click()
                expect(page.locator("#setupGuideDialog")).to_be_visible()
                page.locator("#setupGuideDialog [data-setup-action='dismiss']").last.click()
                assert len(FakeModelHandler.requests) == before_guide

                page.locator("[data-action='open-settings']").first.click()
                page.locator("#providerHubPanel").wait_for(state="visible")
                assert page.locator("#providerKind").input_value() == "minimax"
                page.locator("[data-settings-tab='modelSettingsPanel']").click()
                page.locator("#connectionType").select_option("local_openai")
                page.locator("#connectionName").fill("本地兼容测试")
                page.locator("#connectionProvider").fill("Local OpenAI")
                page.locator("#connectionBaseUrl").fill(f"http://127.0.0.1:{model_server.server_port}/v1")
                page.locator("#connectionModel").fill("local-test-model")
                page.locator("[data-action='save-model-connection']").click()
                page.locator("[data-action='test-model-connection']").click()
                page.locator("#dialogModelResult").wait_for(state="visible")
                page.wait_for_function("() => document.querySelector('#dialogModelResult')?.textContent.includes('成功')")
                assert "成功" in page.locator("#dialogModelResult").inner_text()
                page.locator("#settingsDialog .dialog-close").click()

                page.locator("[data-action='new-real-avatar']").first.click()
                page.locator("#identityForm [name=name]").fill("小满")
                page.locator("#identityForm [name=purpose]").fill("浏览器发布验收")
                page.locator("#identityForm [name=consent_confirmed]").check()
                page.locator("#identityForm button.primary").click()
                page.wait_for_selector("#step2:not(.hidden)")
                page.locator('.upload-card input[data-category="conversation"]').set_input_files(str(chat_file))
                page.wait_for_selector("[data-action='review-import']")
                page.locator("[data-action='review-import']").click()
                page.locator("[data-action='confirm-import']").click()
                page.locator('#realUploadGrid input[data-category="audio"]').set_input_files(str(audio_file))
                page.locator("[data-action='choose-ai']").click()
                page.locator("#modelForm button.primary").click()
                page.wait_for_selector("#step4:not(.hidden)")
                page.locator("#personaForm button.primary").click()
                page.locator("[data-action='open-current']").click()
                page.wait_for_selector("#studioView:not(.hidden)")
                expect(page.locator("#readinessBanner")).to_contain_text("正式可用", timeout=15000)
                page.locator("[data-tab='chat']").click()
                page.locator("#chatMessageInput").fill("请流式回复一句问候")
                page.locator("#sendChatText").click()
                page.wait_for_function("() => !document.querySelector('[data-action=cancel-chat]')")
                expect(page.locator("#messageList .message.assistant").last).to_contain_text("你好，我会依据已经确认的资料回答。", timeout=15000)

                # These actions update local memory only. They keep the original
                # text while reflecting the saved/corrected/disabled state.
                memory_button = page.locator("#messageList .message.user [data-chat-memory]").last
                message_id = memory_button.get_attribute("data-chat-memory")
                memory_selector = f"#messageList [data-chat-memory='{message_id}']"
                before_memory = len(FakeModelHandler.requests)
                memory_button.click()
                page.locator("#chatMemoryContent").fill("我喜欢周六上午去图书馆。")
                page.locator("#chatMemoryForm button[type='submit']").click()
                expect(page.locator(memory_selector)).to_have_text("已记住")
                page.locator(memory_selector).click()
                expect(page.locator("#chatMemoryContent")).to_have_value("我喜欢周六上午去图书馆。")
                page.locator("#chatMemoryContent").fill("我喜欢周日上午去图书馆。")
                page.locator("[data-memory-save='correct']").click()
                expect(page.locator("#chatMemoryDialog")).not_to_be_visible()
                page.locator(memory_selector).click()
                expect(page.locator("#chatMemoryContent")).to_have_value("我喜欢周日上午去图书馆。")
                page.locator("[data-memory-save='forget']").click()
                expect(page.locator(memory_selector)).to_have_text("已停用")
                assert len(FakeModelHandler.requests) == before_memory
                expect(page.locator(f"[data-message-id='{message_id}']")).to_contain_text("请流式回复一句问候")

                # Uploading a TXT does not call the model. Explicit reading and
                # follow-up questions use the local HTTP substitute and show a
                # source button that opens the same selected file again.
                before_document = len(FakeModelHandler.requests)
                page.locator("#toggleChatMore").click()
                page.locator("#chatFilePicker").set_input_files(str(document_file))
                expect(page.locator("#chatAttachmentDialog")).to_be_visible()
                page.locator("#sendChatAttachment").click()
                file_button = page.locator("#messageList .message.user [data-read-document]").last
                expect(file_button).to_have_text("阅读此文件")
                file_id = file_button.get_attribute("data-read-document")
                assert len(FakeModelHandler.requests) == before_document
                file_button.click()
                expect(page.locator("#chatDocumentTitle")).to_contain_text("校园活动.txt")
                page.locator("#chatDocumentConsent").check()
                page.locator("#sendChatDocument").click()
                expect(page.locator("#chatDocumentResult")).to_contain_text("图书馆", timeout=15000)
                expect(page.locator("#chatDocumentResult")).to_contain_text("文件来源：校园活动.txt")
                expect(page.locator("#sendChatDocument")).to_be_enabled()
                assert not page.locator("#chatDocumentConsent").is_checked()
                page.locator("#chatDocumentQuestion").fill("集合时间是什么？")
                page.locator("#chatDocumentConsent").check()
                page.locator("#sendChatDocument").click()
                expect(page.locator("#chatDocumentResult")).to_contain_text("周六上午九点", timeout=15000)
                expect(page.locator("#sendChatDocument")).to_be_enabled()
                assert len(FakeModelHandler.requests) == before_document + 2
                question = json.loads(FakeModelHandler.requests[-1]["messages"][-1]["content"])
                assert question["question"] == "集合时间是什么？"
                assert "图书馆" in question["document"]["text"]
                page.locator("#closeChatDocument").click()
                source = page.locator(f"#messageList .message.assistant [data-read-document='{file_id}']").last
                expect(source).to_contain_text("校园活动.txt")
                source.click()
                expect(page.locator("#chatDocumentTitle")).to_contain_text("校园活动.txt")
                page.locator("#closeChatDocument").click()

                # Inspect settings only: never press Connect or acquire a mic.
                page.locator("#toggleChatMore").click()
                page.locator("[data-chat-tool='call']").click()
                page.locator("#startVoiceCall").click()
                expect(page.locator("#voiceCallMaxMinutes")).to_have_value("10")
                expect(page.locator("#voiceCallBudget")).to_have_value("5")
                page.locator("#voiceCallMaxMinutes").fill("30")
                page.locator("#voiceCallBudget").fill("2.5")
                expect(page.locator("#voiceCallBeforeStart")).to_contain_text("不是服务商账单硬上限")
                page.locator("#closeVoiceWindow").click()

                page.locator("[data-action='open-settings']").first.click()
                page.locator("[data-action='set-interface-language'][data-language='en-US']").click()
                page.locator('html[lang="en-US"]').wait_for(state="attached")
                page.locator("#settingsDialog .dialog-close").click()
                page.set_viewport_size({"width": 390, "height": 844})
                page.locator(memory_selector).click()
                expect(page.locator("#chatMemoryDialog")).to_contain_text("Memory for this message")
                assert page.locator("#chatMemoryDialog").evaluate("node => node.scrollWidth <= node.clientWidth")
                page.locator("[data-memory-close]").click()
                page.locator(f"#messageList .message.user [data-read-document='{file_id}']").first.click()
                expect(page.locator("#chatDocumentTitle")).to_contain_text("File:")
                assert page.locator("#chatDocumentDialog").evaluate("node => node.scrollWidth <= node.clientWidth")
                page.locator("#closeChatDocument").click()
                assert page.locator("html").evaluate("node => node.scrollWidth <= node.clientWidth")
                page.screenshot(path=str(output / "ui-upgrade-english-mobile.png"), full_page=True)
                page.set_viewport_size({"width": 1440, "height": 1000})
                page.locator("[data-action='open-settings']").first.click()
                page.locator("[data-action='set-interface-language'][data-language='zh-CN']").click()
                page.locator("#settingsDialog .dialog-close").click()
                page.locator("[data-tab='training']").click()
                page.wait_for_function("() => document.querySelector('#buildPanels')?.textContent.includes('VISUAL CONTINUITY')")
                expect(page.locator("#buildPanels")).to_contain_text("一致性素材包", timeout=15000)
                page.locator("[data-action='organize-visual-assets']").click()
                page.wait_for_function("() => document.querySelector('#buildPanels')?.textContent.includes('人物 0')")
                page.locator("[data-tab='settings']").click()
                page.locator("[data-action='export-avatar']").click()
                page.wait_for_selector("#packageExportDialog[open]")
                page.locator("[data-action='cancel-package-export']").click()
                page.screenshot(path=str(output / "ui-smoke-desktop.png"), full_page=True)

                page.locator("#studioView [data-action='home']").click()
                page.locator("[data-action='new-fictional-avatar']").first.click()
                page.locator("#identityForm [name=name]").fill("林澄")
                page.locator("#identityForm [name=subject_kind]").evaluate("node => node.value = 'fictional'")
                page.locator("#identityForm [name=world_region]").select_option("north_america")
                page.locator("#identityForm [name=avatar_primary_language]").select_option("en-US")
                page.locator("#identityForm [name=consent_confirmed]").check()
                page.locator("#identityForm button.primary").click()
                page.wait_for_selector("#step2:not(.hidden)")
                page.locator("[data-action='set-fictional-flow'][data-flow='template']").click()
                page.locator('.upload-card input[data-category="fictional"]').set_input_files(str(fictional_file))
                page.wait_for_selector("[data-action='review-import']")
                page.locator("[data-action='review-import']").click()
                page.wait_for_selector("#fictionalApplyModeLabel:not(.hidden)")
                page.locator("#fictionalApplyMode").select_option("merge")
                page.locator("[data-action='confirm-import']").click()
                page.locator("[data-action='choose-ai']").click()

                page.locator("[data-action='open-settings']").first.click()
                page.locator("[data-action='set-interface-language'][data-language='en-US']").click()
                page.locator('html[lang="en-US"]').wait_for(state="attached")
                assert page.locator("html").get_attribute("lang") == "en-US"
                assert "Connection Center" in page.locator("#settingsDialog").inner_text()
                page.locator("[data-action='set-interface-language'][data-language='zh-CN']").click()
                page.locator("#settingsDialog .dialog-close").click()

                mobile = browser.new_page(viewport={"width": 390, "height": 844})
                mobile.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
                mobile.goto(args.base_url)
                mobile.wait_for_load_state("networkidle")
                if mobile.locator("#setupGuideDialog[open]").count():
                    mobile.locator("#setupGuideDialog [data-setup-action='dismiss']").last.click()
                mobile.locator("[data-action='toggle-mobile-menu']").click()
                assert mobile.locator(".top-actions.open").is_visible()
                assert mobile.locator(".top-actions.open").bounding_box()["width"] <= 320
                mobile.locator("[data-action='toggle-mobile-menu']").click()
                assert not mobile.locator(".top-actions").is_visible()
                assert mobile.locator("html").evaluate("node => node.scrollWidth <= node.clientWidth")
                mobile.screenshot(path=str(output / "ui-smoke-mobile.png"), full_page=True)
                assert not console_errors, console_errors
                browser.close()
        print("UI_SMOKE_OK")
        return 0
    finally:
        model_server.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
