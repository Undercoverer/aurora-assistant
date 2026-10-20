# Kev decision waterfall

## Request flow

Aurora uses the actual [Kev model](https://huggingface.co/ggml-org/Kev-4B-GGUF)
through llama.cpp's `/v1/systemone`. Like the
[Jev reference](https://github.com/browser-use/jev-ultrafast), it separates selecting
observed controls from generating text. No hosted Jev service is used.

1. Read `org.aurora.Desktop1.Describe` over D-Bus for live action descriptions and
   argument schemas. Native introspection adds observed methods and properties.
2. Supply a stable catalog, independent of request wording. With more than 32
   actionable documents across multiple interface groups, Kev first chooses a group.
3. Kev chooses one operation covering the entire request. Negation, conditions,
   uncertainty and multiple operations must trigger escalation.
4. Derive finite argument choices from the advertised schema: constants, booleans,
   enums or bounded integer ranges of at most 128 values. Kev selects the value
   semantically. Volume supplies all values 0–100; number words need no parser.
5. Each stage requires a valid probability distribution and a unique winner above
   `kev.threshold`. Unknown indices, uncertainty, malformed responses or free-form
   arguments hand off to Qwen. No intermediate stage executes anything.
6. Qwen handles free-form arguments, multiple actions, further discovery and
   clarification. The complete plan passes typed validation. Invalid plans get one
   correction attempt within the existing turn limits.
7. Prepare live targets, apply local policy and safety review, then execute approved
   actions with existing owner checks and readback. Completion replies use results.

This is bounded to three routing decisions, not recursive execution. There are no
hardcoded request phrases, digit extraction or predefined website candidates in
this routing path. Multi-action requests remain supported through Qwen.

## Examples

These are intended paths, not a claim of measured model accuracy.

| Request | Available path |
| --- | --- |
| What time is it? | Advertised `desktop_read clock`, returning the actual host clock over D-Bus |
| Silence the speakers | Advertised `mute`, then boolean selection |
| Make the loudness twelve percent | Advertised `volume`, then selection from 0–100 |
| Open YouTube | Advertised `open_url`; Qwen generates the URL, followed by validation and portal opening |
| Mute the microphone and pause playback | Qwen prepares two actions; microphone mute executes last |
| Use Breeze Dark | Discover installed theme/color IDs, then select an observed ID |

Routine policy accepts validated prepared volume/mute, microphone mute, media and
URL actions when no adapter requires approval. It is wording-independent and trusts
the validated plan's interpretation; it is not an independent proof of intent.
Generic D-Bus mutations still require approval. Confidence cannot override adapter
approval requirements. Local approval is not root privilege escalation.

Controller-to-desktop calls use D-Bus. MPRIS and portal operations are native D-Bus.
Some adapter operations still invoke fixed `wpctl` or KDE commands internally.
There is no unrestricted shell tool, nor a claim that every setting has a native
KDE D-Bus method.

## Context and cache

```nix
programs.aurora-assistant = {
  enable = true;
  user = "foxkj"; # Existing Plasma account.
  models.wakeWord = "alexa";
  kev = {
    model = "hf.co/ggml-org/Kev-4B-GGUF:Q4_K_M";
    contextSize = 32768;
    cacheRamMiB = 512; # Explicit decision prompt-cache opt-in; 0 disables.
    threshold = 0.95;
  };
  safety.backend = "kev";
  planner.model = "hf.co/Qwen/Qwen3-4B-GGUF:Q4_K_M";
};
```

All stages reuse the same state string: sorted catalog, then observations, then
user request. Stage-specific questions follow it. This enables prefix reuse without
inventing an HTTP `cache_prompt` field for the decision endpoint. Changed state,
eviction and backend behavior affect cache hits. External servers need their own
context/cache configuration. Additional decisions add overhead; speedups have not
been measured here.

The [upstream card](https://huggingface.co/jaredpalmer/kev-4b) describes a served
context larger than 32K but validation at 8K. Configuring 32K capacity does not prove
equal accuracy at that length. Larger input uses the local tokenizer with a
2,048-token template reserve; this is an estimate, and the server remains the
final capacity check. Overflow escalates without truncating intent. Requests over
8,192 characters are rejected before planning.

## Diagnostics and validation

```sh
aurora-control capabilities > aurora-capabilities.md
aurora-report --since '10 minutes ago' --clipboard
```

`kev.decision` times each call; `kev.selection` records confidence/acceptance;
`kev.escalate` identifies empty catalogs or generation requirements.
`kev.route_failed` records failures. `capabilities.refresh_failed` means stale
adapter metadata was cleared. `review.local` shows routine policy and
`plan.invalid` shows static validation errors.

Tests cover stable menus, nested index mapping, finite domains, malformed decisions,
context overflow, stale metadata, approval preservation and plan correction.
Inference is mocked: tests do not prove semantic accuracy or latency. Live D-Bus
tests need an isolated session bus. NixOS, Plasma and actual Kev behavior need
validation on the target host.
