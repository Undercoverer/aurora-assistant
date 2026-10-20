# Request processing and service boundaries

1. openWakeWord activates the microphone turn. Silero detects speech boundaries.
   RealtimeSTT/faster-whisper supplies provisional replacements and final text.
2. Kev gets up to two decision rounds by default to select fully specified actions.
   Explicit absolute volume, mute and playback requests can take this path. Observed
   argument-free D-Bus methods and readable properties are also candidates.
   Unresolved identifiers or uncertain intent go to the larger `planner.model` planner.
   Routing has a configurable 10-second HTTP timeout, not a guaranteed response-time target.
3. The larger planner can discover services, objects, properties, themes, and apps
   over bounded rounds. Read results are untrusted data. A discovery round never
   executes accompanying mutations. Preparation errors feed back to the planner.
4. Every final mutation batch is prepared before execution. The separate reviewer
   sees the original request and exact operations. Generic changes always need
   human approval; model confidence cannot remove this requirement.
5. The executor sends typed native D-Bus calls where available, or calls the Aurora
   desktop adapter for non-native controls. Up to four mutations run sequentially.
   A failure stops subsequent operations. Earlier changes are not rolled back.
6. The overlay and local TTS communicate the observed result. A successful method
   return is distinguished from independently verified state.

Kev and Qwen share one llama.cpp router endpoint and systemd unit. The router
starts separate model worker processes using the same installed package.
Kev uses `/v1/systemone`; the planner uses `/v1/chat/completions`. Review defaults
to Kev in a separate decision request. `safety.backend = "planner"` uses the planner
in a separate tool-free context instead. Reusing weights does not provide independent
judgment. A failed Kev route falls back to the planner; a failed review asks for
approval. No Ollama service is managed or contacted.

| Service | Manager | Responsibility |
| --- | --- | --- |
| aurora-inference | User | llama.cpp router and Kev/Qwen workers, loopback port 8008 |
| aurora-models | System, configured user | Download and validate named assets during provisioning |
| aurora-desktop | User | D-Bus adapter for desktop backends and installed applications |
| aurora-voice-overlay | User | Qt/QML visuals and pinned D-Bus interface |
| aurora-tts | User | Local OpenAI-compatible Supertonic speech API |
| aurora-controller | User | Microphone pipeline, routing, discovery, review, execution, response |

`aurora-assistant.target` groups the user services under the graphical session.
The system model provisioner and user session are distinct systemd managers;
offline manifest checks gate the inference services while assets are incomplete.
Stopping the target stops its user services, including the router and both model workers. It does
not delete model files.

The overlay contract is unchanged. No KWin effect, new approval dialog, barge-in,
persistent conversation memory, or arbitrary file editor is included in this update.

When webSearch.enable is true, the larger planner can return one standalone
web_search action. Its results enter a separate tool-free summarizer and terminate
the turn. The desktop planner never receives web evidence. See WEB_SEARCH.md.

Escalation can speak a short notice while the larger planner is already running.
Reply captions use locally aligned word timings and the playback device clock.
See [SPEECH_FEEDBACK.md](SPEECH_FEEDBACK.md) for configuration and timing limits.
