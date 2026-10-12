# Dev PC voice acceptance recipe

This is a short user-assisted test of the committed native app. Start it only when Krish is ready to speak. Nothing in this recipe connects to Claude or launches anything on Deployment PC. The microphone stays off until explicit conversation selection or explicit recognition-test start; close the app when the test ends.

## Verified preparation

- The installed en-US System.Speech recognizer processed six offline synthetic WAV files. Silence, resume, shutdown and explicit force-close matched the control grammar; two unrelated phrases matched dictation.
- The actual recognized final events were passed through the native page's JavaScript using a fake host and fake playback. They reached the intended controls; unrelated phrases reached the local-turn route.
- These are injected-audio results, not proof of Krish's microphone speech or audible playback. A separate one-second real microphone lifecycle check reached listening and stopped cleanly.
- The real native text save/reopen/context/close path was verified with the same owned store below. No live Claude request was sent.

## Launch when ready

Run this in PowerShell on this Dev PC. The runtime is the existing task-owned environment; no installation or download is required. Each launch gets a fresh browser profile while retaining the already verified demo conversation store.

```powershell
$voiceDemoRepo = 'C:\Users\Krish\.codex\worktrees\e396\my-ai'
$voiceDemoPython = 'C:\Users\Krish\AppData\Local\Temp\jarvis-ui-runtime-3e233709-1c1a-427e-b776-b45cd98b599b\Scripts\python.exe'
$voiceDemoRoot = 'C:\Users\Krish\AppData\Local\Temp\jarvis-native-durable-95bf3a92-f8e4-455f-98bc-684063248aea'
$voiceDemoRun = Join-Path $voiceDemoRoot ('voice-' + [guid]::NewGuid().ToString())
New-Item -ItemType Directory -Path $voiceDemoRun | Out-Null
$voiceDemoProcess = Start-Process -FilePath $voiceDemoPython -WorkingDirectory $voiceDemoRepo -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $voiceDemoRun 'stdout.txt') -RedirectStandardError (Join-Path $voiceDemoRun 'stderr.txt') -ArgumentList @(
  '-m', 'jarvis_voice.native_host',
  '--comm-root', (Join-Path $voiceDemoRoot 'comm'),
  '--store-root', (Join-Path $voiceDemoRoot 'store'),
  '--participant', 'jarvis-durable-owned', '--peer', 'unbound-owned-fixture',
  '--profile-root', (Join-Path $voiceDemoRun 'profile'),
  '--local-model', 'hermes3:8b', '--microphone', '--speech'
)
```

If the runtime or fixture directory has been moved, stop and refresh these paths. Do not silently substitute another store or runtime.

## One-minute user script

Use headphones for the initial test. Confirm the UI initially says the microphone is off for setup. **Silence** controls output; the separate recognition-test buttons control the diagnostic below.

1. Type **Jarvis list conversations**, press Enter, then type **Jarvis resume conversation 1** and press Enter. Check that the Sapphire conversation appears and the microphone then changes to listening. Recognition is displayed separately and never overwrites manually typed text.
2. Say **Jarvis, back to voice mode**. Check that speech changes to enabled.
3. Say **What is my project codename?** Wait for the final transcript and the answer. Expect Sapphire, one user turn, one saved local answer, and audible output.
4. Say **Describe a garden in three sentences**. While its reply is audible, say **Silence**. Check that output stops, the microphone remains listening, and no old output resumes by itself.
5. Say **What is two plus two?** The answer should appear while output remains silent.
6. Say **Jarvis, back to voice mode**, then ask **What is three plus three?** Only the new reply should be audible; no earlier reply should replay.
7. Once the answer finishes, say **Jarvis, shut down**. Confirm the window closes. A failed or uncertain save must leave it open with an explanation.

Record actual heard text, whether output stopped, whether listening continued, and whether the window closed. Do not count a typed substitute as a successful spoken-command test.

## Stop and recovery

- **Silence** stops output, not microphone capture. Close the app to end microphone capture.
- If recognition misses a command, type **Jarvis shut down** and press Enter. The title-bar Close button uses the same save guard.
- If saving fails, leave the app open to inspect/retry. Only when intentionally abandoning this owned demo's unsaved work, type **Jarvis close without saving** and press Enter.
- If the owned app is completely unresponsive, the PowerShell variable `$voiceDemoProcess` identifies this launch. As a last resort, `Stop-Process -Id $voiceDemoProcess.Id` terminates that launch without a clean-save guarantee. Never stop all Python processes.
- Stop the trial if another app reports a microphone/device conflict. Do not change device permissions or system audio settings as part of this test.

## Remaining acoustic limits

Synthetic WAV recognition does not establish accuracy for Krish's voice, room noise, distance or microphone. There is no accepted acoustic echo-cancellation result: speaker output may be picked up as fresh input, so headphones are the initial baseline. Barge-in currently reacts to recognized final commands, not the onset of speech; interruption latency and recognition while output is playing remain unmeasured. The always-listening session is not a validated wake-word system. Do not leave it capturing unattended.

Evidence: `C:\Users\Krish\AppData\Local\Temp\jarvis-synthetic-voice-a446ae53-feb9-4a8c-b08b-64f6713d4f9a\recognition.json`, `recognition-before.json`, `recognize_wav.py`, and `route_recognized.cjs`. The earlier baseline misrecognized shutdown as “Jervis shutdown”; adding the existing shutdown phrases to the control grammar corrected that synthetic case. No paid inference, download, microphone capture or audible playback was used in this synthetic test.


## Recognition-only diagnostic

In a fresh setup window, click **Start recognition test**, or type **Jarvis recognition test** and press Enter. This explicitly starts microphone capture without choosing or writing a conversation. Wait for the moving orb and **READY — Read sentence 1** before speaking. The orb is paused during setup, processing and results; readiness requires the microphone to report listening. Use **Next sentence** or **Repeat sentence** to set each trial boundary. Background speech and recognizer chunks never advance the sentence number. Every final recognizer result is displayed verbatim in its own numbered entry, with grammar and confidence when available. A spoken sentence can produce multiple results; result numbers are not assumed to be sentence numbers. Spoken commands, requests to Claude, and model inference are all disabled in this mode. No raw audio is recorded.

Click **Stop test**, or type **Jarvis stop recognition test** and press Enter, to end capture. It also stops automatically after two minutes or forty results. Results remain in the window for review; they are not saved into the conversation store. Close the window after review and restart for normal voice use. This diagnoses recognition; it does not train the recognizer automatically.

## Typed reopen and save-refusal scope

Dev's finite `REOPEN-RESTORE-WALKTHROUGH.md` at private coordination commit `ff8dfa2` describes the accepted 0022/R4 contract. Reuse this launch and store: type a question, confirm its saved linked local answer, close cleanly, reopen, explicitly select the conversation, then ask the follow-up. Restored event identities and answer-to-user links must remain intact, with no speech replay. The native UI requires explicit selection or creation even on a fresh store; this is intentionally stricter than the API's implicit first-conversation behavior. This local demo does not require Start / Connect or publish a Claude question.

For the negative case, use an isolated failing-store fixture, never alter the live demo store or fill a disk. A failed answer save must expose its unsaved event id, refuse selection/new-conversation while unsaved, and prevent normal close; inspect the actual persistence error and retry only after the fixture recovers. The existing native API checkpoint-failure guard/retry check and Noop native-window close refusal provide separate evidence. They do not establish that the entire failed-answer-save sequence has been demonstrated visibly with the real durable store; that specific user-visible negative remains unverified. No repeat suite is required merely to reuse this recipe.
