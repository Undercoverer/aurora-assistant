# Kev feedback and spoken-word captions

These features apply to ordinary replies and escalation notices. The pinned
VoiceOverlay1 interface does not change: SetMessage receives a growing prefix
of the reply, and SetLevel receives the envelope of audio at playback time.

## Configuration

```nix
programs.aurora-assistant = {
  kev = {
    enable = true;
    model = "hf.co/ggml-org/Kev-4B-GGUF:Q4_K_M";
    maxRounds = 2;
    announceEscalation = true;
    escalationMessage = "Checking that in more detail.";
  };
  ollama.model = "qwen3:4b";
  wordSync = true;
};
```

Kev is the actual decision model, served locally at `/v1/systemone`. It scores
supplied choices; it does not generate commands or arbitrary arguments. Complete
common commands such as "raise the volume to 12" supply deterministic candidates.
Observed D-Bus property reads and methods without input arguments can also be
selected by Kev from the [capability catalog](CAPABILITIES.md). Other requests,
including unknown apps/themes and methods needing arguments, use the larger
planner. The default reviewer uses Kev's noul decision in a separate request.
Generic D-Bus mutations still require local approval.

maxRounds counts toward the overall settings.maxRounds limit. Invalid replies,
uncertainty, preparation failures, or the Kev round limit send the remaining work
to the larger planner. Increasing the limit can avoid large-model calls, but also
increases delay if the smaller model cannot solve the request. No measured latency
or accuracy claim is made for a particular model/hardware combination.

## Escalation notice

The larger planning request starts immediately. If it is still running after
350 milliseconds, the assistant speaks the configured notice once. Fast results
skip it. Audio synthesis and planning overlap; they can contend for local compute.
A notice has an eight-second deadline including synthesis. Failed feedback does
not fail planning. Notice playback finishes or is cancelled before actions and
final-response speech, so the two utterances do not overlap. There is no repeating
"still thinking" message. Disable announceEscalation to keep escalation silent.

## Word timing

The pinned Supertonic SDK returns audio and total duration, not per-word times.
Aurora synthesizes bounded text chunks, then uses faster-whisper's forced alignment
on the supplied text and generated waveform. This is not retranscription, and it
is not an even-spacing or character-count animation. Alignment is local and reuses
the installed realtimeSttModel weights; the TTS service loads another model instance.
No additional model download or cloud alignment service is used.

The controller reveals words at their estimated start times using PortAudio DAC
buffer timestamps and the stream clock. Captions therefore follow playback time,
not HTTP response arrival, model token generation, or submission of audio buffers.
The visual update loop runs at about 30 Hz. Audio-driver timing, Bluetooth delay,
alignment error, compositor latency, and D-Bus delivery can still affect perceived
synchronization. Word boundaries are estimates, not guaranteed exact timestamps.

If a chunk cannot be aligned or exceeds the alignment window, its complete text
appears at the chunk's playback start. The response identifies this as chunk
fallback. It does not invent word timestamps. Disabling wordSync displays the
whole reply at playback start and removes alignment work from the TTS service.
Cancellation aborts queued playback and stops caption updates.

This version prepares audio and alignment before playback begins; it does not
stream LLM output into incremental TTS. Chunking and alignment add preparation
latency and can affect prosody. Native TTS word marks would be preferable if a
future speech backend provides them. Real audio timing, model alignment, and
Wayland visual behavior require target-machine testing.

## Local API extension

The standard `POST /v1/audio/speech` WAV response is retained. Aurora additionally
provides `POST /v1/audio/speech/timed` with the same request fields. It returns:

```json
{
  "audio": "BASE64_ENCODED_WAV",
  "format": "wav",
  "text": "Hello there.",
  "words": [
    {"start": 0.12, "end": 0.4, "charEnd": 5},
    {"start": 0.44, "end": 0.9, "charEnd": 12}
  ],
  "timing": ["aligned"]
}
```

The numbers above illustrate the format. charEnd is an exclusive Python Unicode
code-point offset into text, not a UTF-8 byte offset. Times are seconds from the
beginning of the returned audio. timing contains one aligned/chunk status per
synthesis chunk. Clients validate bounded, monotonic times and text offsets.
A replacement speech server that returns 404/405 for this extension falls back to
the standard WAV endpoint with full-text captions at playback start.

For manual service runs, pass
`aurora-tts --model-dir /var/lib/aurora-models/current/supertonic --model supertonic-3 --alignment-model /var/lib/aurora-models/current/whisper-realtime`.
The Nix module supplies this argument automatically when wordSync is enabled.

## Visibility and clarification

The overlay stays active through planning, execution and speech, then displays
results for `presentation.resultSeconds` (6 by default). Errors remain for
`presentation.errorSeconds` (10). A no-action reply ending in a question mark
opens a wake-word-free follow-up window for `conversation.followUpSeconds` (12),
up to `conversation.maxFollowUps` (2) consecutive replies. This punctuation-based
clarification detection is intentionally limited; it is not open-ended chat.
The conversation is kept only in memory and cleared when the turn finishes.
