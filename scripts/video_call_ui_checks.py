"""Exercise call failures and speech consent without devices or provider requests."""
import argparse
from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', required=True)
    args = parser.parse_args()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(args.base_url)
            page.wait_for_load_state('networkidle')
            results = page.evaluate('''async () => {
                const original = {api, prepareUserMedia, connectNorthLiveKit,
                    confirm: window.confirm, Recognition: window.SpeechRecognition};
                const result = [];
                try {
                    state.currentId = 'isolated-call-check';
                    window.confirm = () => true;
                    for (const scenario of ['create-failed', 'connect-failed', 'end-failed']) {
                        const stopped = [];
                        state.videoCall = null;
                        prepareUserMedia = async () => {
                            state.callCameraEnabled = true;
                            state.userMedia = {getTracks: () => ['video','audio'].map(kind => ({stop: () => stopped.push(kind)}))};
                        };
                        let ended = false, cleanedBeforeEnd = false;
                        api = async (url) => {
                            if (url.endsWith('/end')) {
                                ended = true;
                                cleanedBeforeEnd = stopped.length === 2 && state.userMedia === null;
                                if (scenario === 'end-failed') throw new Error('simulated release failure');
                                return {};
                            }
                            if (scenario === 'create-failed') throw new Error('simulated create failure');
                            return {id:'isolated-session', video_call:{livekit:{}}};
                        };
                        connectNorthLiveKit = async () => {throw new Error('simulated connection failure');};
                        let rejected = false;
                        try {await startVideoCall();} catch (_) {rejected = true;}
                        result.push({scenario, rejected, stopped: stopped.length,
                            cleaned: state.userMedia === null && state.videoCall === null && !state.videoCallStarting,
                            expectedEnd: scenario === 'create-failed' ? !ended : ended && cleanedBeforeEnd,
                            remoteFailureVisible: scenario !== 'end-failed' || document.querySelector('#videoCallStatus').textContent.includes('远程会话释放失败')});
                    }
                    let constructed = 0, started = 0;
                    window.SpeechRecognition = class {constructor(){constructed++;} start(){started++;}};
                    window.confirm = () => false;
                    listenVideoTurn();
                    result.push({scenario:'speech-declined', passed: constructed === 0 && started === 0});
                    window.confirm = () => true;
                    listenVideoTurn();
                    result.push({scenario:'speech-consented', passed: constructed === 1 && started === 1});
                } finally {
                    api=original.api;prepareUserMedia=original.prepareUserMedia;
                    connectNorthLiveKit=original.connectNorthLiveKit;
                    window.confirm=original.confirm;window.SpeechRecognition=original.Recognition;
                    state.userMedia=null;state.videoCall=null;state.speechRecognition=null;
                }
                return result;
            }''')
            for result in results:
                if 'passed' in result:
                    assert result['passed'], result
                else:
                    assert result['rejected'] and result['stopped'] == 2 and result['cleaned'] and result['expectedEnd'] and result['remoteFailureVisible'], result
            print('VIDEO_CALL_FAILURE_AND_SPEECH_CONSENT_OK')
        finally:
            browser.close()


if __name__ == '__main__':
    main()
