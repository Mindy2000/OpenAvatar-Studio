# Quick start

[中文](QUICKSTART.md) · [User guide](GUIDE_EN.md) · [Home](../README_EN.md)

Start from an empty avatar list, configure a service, create an avatar, and send a first message. Then try voice, photos, and saving. Fresh installations contain no demo avatars, photos, or custom voices. Prepare your own, explicitly authorized, or original fictional materials. The [user guide](GUIDE_EN.md) is the full reference for features and configuration.

## 1. Start the application

Follow the [installation instructions](GUIDE_EN.md), run the desktop launcher or source script, and open the local URL shown by the launcher. Keep the launcher or service terminal running; do not open the project's HTML file directly.

**Done when:** The avatar home page appears. If existing avatars are missing, check the launcher's data directory first: source and desktop installations use different defaults.

## 2. Configure a chat service first

Prepare a provider account, an available model, and an API key. Cloud analysis, chat, image understanding, synthesis, and generation may incur charges. Browser speech recognition may also use the browser's own online service.

1. Open Global AI Settings → Services and capability routes, and create a connection.
2. Enter the provider, URL, and dedicated API key field. Do not put the key in character settings, URLs, or advanced JSON.
3. Enable Chat first, enter a supported model, authorize text transmission, and save the connection.
4. Select that connection and model for the Chat capability, save the route, and check that the connection is enabled.
5. Review Ability Status. If something is unavailable, use Diagnostics to check the key, model, consent, budget, and provider balance.

Add Speech Synthesis for spoken replies, or Vision with image consent for understanding photos. Browser-recognition voice notes and calls do not require the separate file-transcription capability to be configured first.

**Done when:** The saved connection and routes remain visible and the required capabilities meet their readiness conditions. A connection check does not prove every feature has made a successful real request; the reply in section 5 establishes your first chat result.

Budgets use estimates and cannot guarantee a hard cap on actual bills. Unified service-hub voice-cloning routes have specific estimate validation and pre-call budget checks; the legacy Aliyun path does not have equivalent checks. Read the [cost and data boundaries](PRIVACY_EN.md) before cloning.

## 3. Create an avatar and complete required items

For a first experience, use an original fictional character. If you have authorized materials for a real person, choose the real-material creation path instead.

1. On the home page, choose Create fictional avatar. Fill in the name, relationship, language, world setting, and material rights.
2. Answer the identity, personality, speaking-style, and boundary questions, saving each item. Skip unnecessary complex world modules for now.
3. Choose the AI method and use the configured connection. Review the resulting profile, correct it, and save and continue. If analysis requires a connection, complete section 2 first.
4. In the studio's Build Center, check settings and follow the prompts to complete required items. Run the unified Builder when the build result needs updating.
5. Confirm that the avatar says Ready for official use before starting everyday chat. Recommended and advanced items can follow later.

**Done when:** The profile matches your settings, required items pass, and Ready for official use appears. Readiness determines this state; there is no separate Activate avatar button. In Preview test mode, check whether materials or a model are missing. Preview and official chats are stored separately.

## 4. Use existing materials, photos, and voices

Choose the entry point by what the file contains:

| Content | Action | Check afterward |
|---|---|---|
| Character settings | On the fictional path, import a completed template. Review extracted fields and merge/replace mode, then confirm for building | Character summary, speaking style, boundaries, and world settings |
| Chat history | Upload through Chat records on the real-material path. Review speakers, exclude unwanted rows, and confirm | Confirmed history, evidence, and memories |
| A complete avatar package | Import `.openavatar.zip` from the home page, read the preflight, and confirm material rights | The imported avatar and included content |

For an existing fictional avatar, continue importing from Persona & Materials. The fictional-settings path does not expose the same chat-history upload entry; do not import a chat log as a character template. If you download the combined template file, save only its Markdown or YAML section before filling it in. Alternatively, use the repository's [Markdown](templates/avatar.md) or [YAML](templates/character.yaml) template.

**Use your photos:** Upload through the material page's visual-candidate or photo entry. Inspect the candidates in Build Center, approve suitable images, and set the main identity reference to canonical. Existing suitable photos do not need regeneration. A chat photo and an identity reference serve different purposes.

**Choose a voice:** Configure a MiniMax Speech Synthesis route, then select a supported preset in Build Center. Selection itself makes no cloud call and is not voice cloning; playing a reply synthesizes speech and incurs charges. A new installation does not automatically include custom voices used in someone else's demonstration.

**Done when:** Imports are confirmed and visible in the relevant records, the main image is canonical, and the intended voice is selected. Uploading is not approval, and selecting a voice does not establish that its audition succeeded.

## 5. Send a first official message

1. Open Chat, enter a short question that checks the character settings, and send it.
2. Watch the reply appear and check identity and speaking style. Ordinary text and voice-note replies are limited to 80 characters, including punctuation.
3. To hear the reply, use its playback control and confirm the charge. Reading text alone does not require speech synthesis.
4. Return home and reopen the same avatar to check that the message and reply remain.

**Done when:** A complete reply is saved in the official chat and can be reopened. If a request fails, read the error and check routing and quota before deciding to retry, rather than sending repeated requests.

## 6. Use voice notes, photos, and the + panel

| Goal | Steps | Result and boundaries |
|---|---|---|
| Send a voice note | Switch to the microphone beside the input. Hold to speak, release to send, or slide up while holding and release to cancel | The voice note plays back. Recognized text triggers a reply; without text, only the recording is saved and you can add a text message. Under 0.5 seconds is discarded; the maximum is 60 seconds |
| Take or send a photo | Choose + → Camera or Images / Video. Selfies are mirrored by default; disable this if needed. Review and send | Preview and sent orientation match. With a Vision route, the photo is read and answered, potentially incurring charges. Saving a photo is not proof of image understanding |
| Understand an older photo | Use the image-understanding action beside the photo | A success marker appears. Successful results are reused; failures require manual retry. Chat image understanding is separate from material OCR |
| Send a video or file | Choose + → Images / Video or Files, preview, and send | Videos play and files download; their contents are not automatically interpreted |
| Send a location | Choose + → Location, enter a name and address, and send | A card displays the manually entered location; there is no automatic or continuous location sharing |
| Save and resend a favorite | Click ☆ beside a message, then choose it from + → Favorites and send | The original appears in favorites and a resent message appears in chat |

Each attachment is limited to 50 MB and the current upload setting. A photo sent in chat does not automatically become persona material. For microphone or camera problems, check browser site permissions. Use text if recognition is unsupported.

## 7. Make a voice call

First check that Chat and Speech Synthesis work, a voice is selected, and microphone access is allowed. Headphones are recommended.

1. Choose + → Calls → Voice in the chat composer, read the notice, and start the call.
2. Say something and wait for the reply. To change the topic, speak directly or use Interrupt reply, then say the new message.
3. Use the microphone control to mute/unmute. Use the — control to minimize, then click the floating window to return.
4. Hang up and check the resulting call card in chat.

**Done when:** You hear the selected voice; interruption stops the old reply and continues with the new message; mute and window states work; and recording stops on hangup. Calls are limited to three turns and ten minutes. Hiding the page or switching avatars ends the call.

The call window and ordinary chat history do not display per-utterance call transcripts. Those transcripts remain stored locally and may enter later model context. Ordinary voice notes remain visible. Video calls share the Calls menu but need separate North/Atlas configuration; they are not a prerequisite for your first voice call.

## 8. Save, migrate, and organize later

1. Open Settings & Export → Export full avatar package. Select conversations, audio, images, video, and call history, then generate and download.
2. Check that you have a `.openavatar.zip`. To migrate, import it from the home page, review the preflight, confirm rights, and inspect the settings and selected assets.
3. Keys do not migrate with the package. External voice or visual assets may need their service bindings restored.

**Done when:** The package downloads and passes preflight, and the imported avatar and selected content can be opened. Disabling call history excludes call transcripts, cards, sessions, and reply diagnostics. Older synthesized audio lacks purpose labels, so generated audio, including old auditions, is also excluded. Original recordings and voice-note attachments still follow the audio option.

An avatar package does not replace a full database backup. Settings & Export → Data maintenance offers database backups, memory editing/approval, duplicate merges, and revision history. Life Archive offers runtime-chat editing, archiving, and restoration. Database restore affects every avatar in the current data directory, requires confirmation text, and first creates a safety backup; it does not replace media files or system credentials. See the [user guide](GUIDE_EN.md) and [package protocol](OPENAVATAR_PACKAGE_EN.md) for details.

Voice cloning, world-fact approval, clothing/scene continuity assets, and asynchronous video are later, advanced workflows. Configure them when needed; getting started does not require every service or regeneration of assets you already like.
