# Request processing and service boundaries

1. openWakeWord activates the microphone turn. Silero detects speech boundaries.
   RealtimeSTT/faster-whisper supplies provisional replacements and final text.
2. Kev gets one attempt to fill common typed actions. Explicit absolute volume,
   mute, and playback requests can take this path. Unknown identifiers, relative
   adjustments, or uncertain intent go to the larger `ollama.model` planner.
   Routing has a 15-second HTTP timeout, not a guaranteed response-time target.
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

Kev, the larger planner, and the reviewer are roles, not necessarily three loaded
models. By default they use the same configured Ollama tag. Set `kev.model` to a
smaller local model if desired; `safety.model` controls the review role. Reusing
weights does not provide independent judgment. A malformed or failed Kev answer
falls back to the larger planner without executing it. A failed reviewer asks for
local approval. Model preparation includes every enabled role by name.

| Service | Manager | Responsibility |
| --- | --- | --- |
| ollama | System | Local model inference, loopback only |
| aurora-models | System, configured user | Download and validate named assets during provisioning |
| aurora-desktop | User | D-Bus adapter for desktop backends and installed applications |
| aurora-voice-overlay | User | Qt/QML visuals and pinned D-Bus interface |
| aurora-tts | User | Local OpenAI-compatible Supertonic speech API |
| aurora-controller | User | Microphone pipeline, routing, discovery, review, execution, response |

`aurora-assistant.target` groups the user services under the graphical session.
The system model provisioner and user session are distinct systemd managers;
offline manifest checks gate the inference services while assets are incomplete.
Stopping the target stops its user services. It does not stop the system Ollama
service or delete model files.

The overlay contract is unchanged. No KWin effect, new approval dialog, barge-in,
conversation memory, or arbitrary file editor is included in this update.
