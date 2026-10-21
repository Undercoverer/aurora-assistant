# Discovered D-Bus capabilities

The controller reads `org.aurora.Desktop1.Describe` over the session bus. This
versioned JSON description comes from the running desktop adapter's unique owner
and advertises operations, descriptions and argument schemas. It is additive to
the desktop service; the pinned overlay API is unchanged.

Read-only startup discovery lists running services and follows observed child
paths. One scan attempts at most 24 objects, seeds at most 150 services per bus,
and has a six-second budget. It runs before voice capture starts.
Set settings.discoveryMode to "periodic" to restore the older four-minute crawl.
settings.scanMaxObjects and settings.scanTimeoutSeconds control the fixed bounds.
The MCP backend uses machine-readable describe_object, list_services and
read_property results. These read tools never authorize mutations.
Empty roots do not evict useful observations. Coverage is partial;
the planner can inspect additional objects on demand. Generic discovery follows
bus policy and is disabled when settings support is disabled.

Native introspection supplies bus, service, path, interface, member, signature and
access. Application/theme/color reads supply installed IDs. Native observations
retain at most 16 objects; the combined catalog exposes at most 256 documents.
Startup observations remain planning hints for the session and are replaced on reinspection.
Periodic mode expires entries after five minutes. Adapter
metadata is refreshed before planning and cleared on refresh failure.

Kev receives up to 254 stably sorted documents, independent of user wording.
Large menus can use interface-group selection before operation selection.
Readable properties, no-input methods and writable boolean properties supply
concrete candidates. Adapter schemas supply finite argument domains. Free-form
arguments and multiple actions go to Qwen. See the [workflow](DECISION_WORKFLOW.md).

The planner additionally receives a small lexical shortlist. Optional offline embeddings can supplement this shortlist; see
[recall evaluation](RECALL_EVALUATION.md). They do not replace Kev or policy. Signatures alone do not establish meaning, units, ranges or side effects.
Generic mutations still need live introspection, validation, owner checks and
approval. Some adapter operations use fixed native utilities internally.

While the controller is running:

```sh
aurora-control capabilities > aurora-capabilities.md
```

The private same-user socket exports metadata and descriptions, not property
values or recordings. It can reveal application/service names and is capped at
90,000 characters. This is a diagnostic snapshot, not executable configuration.
For empty exports or refresh failures, check `aurora-desktop.service` and the
merged report before interpreting model behavior.


## Idle-time semantic catalog

The local planner can add plain-language explanations to live native methods and
properties. These are explicitly marked `model_inferred_unverified` and include
unknowns. Introspection types alone cannot establish purpose, units, ranges or
side effects. The model cannot create action mappings, argument ranges, approvals,
or executable code through this channel. Existing candidates still come only
from observed interfaces or the desktop adapter's advertised schemas.

The NixOS defaults are:

```nix
programs.aurora-assistant.catalog = {
  enrich = false;
  persist = true;
  idleSeconds = 60;
  intervalSeconds = 240;
  timeoutSeconds = 15;
};
```

Only one member is explained per interval. Failures have a one-hour retry delay.
No explanation request runs until the assistant has been idle for the configured
period. Wake/partial-speech events and foreground requests cancel the client task;
no work is scheduled during a turn or clarification wait. Cancellation of actual
server compute is backend-dependent, so zero contention is not guaranteed. Disable
`catalog.enrich` if the extra local work affects voice latency. No extra model or
service is installed; enrichment uses the existing local planner with no tools.

The private cache is `$XDG_CACHE_HOME/aurora-assistant/capability-notes.json`, or
`~/.cache/aurora-assistant/capability-notes.json` by default. It stores at most 512
explanations, with a one-MiB file cap and seven-day lifetime. A fingerprint includes
bus, destination, path, interface, member, type signatures and argument names.
Changed signatures or planner model aliases invalidate reuse. Changing model
weights under the same alias does not immediately invalidate notes; clear the cache
when needed. Identical signatures also do not prove identical behavior after an
application update. Notes remain hypotheses even when reused.

No executable capability is restored from disk. The same member must be observed
again before its explanation appears. Corrupt/oversized cache files are ignored;
writes are atomic and private. The cache contains no transcript or read property
values, but generated descriptions may reveal installed service/application names.
Set `persist = false` for memory-only notes. To erase saved notes, stop the controller,
remove the cache file, then restart; leave enrichment disabled to prevent regeneration.

```sh
aurora-control catalog-status
aurora-control capabilities > aurora-capabilities.md
```

The export labels inferred explanations separately. `catalog.explanation_saved`,
`catalog.explanation_failed` and `catalog.save_failed` provide diagnostics without
logging generated text. Discovery remains bounded and partial, with a 16-object
live cache and a 256-document export limit. This is not a
complete KDE knowledge base, a vector search index, or proof of semantic accuracy.

The [D-Bus specification](https://dbus.freedesktop.org/doc/dbus-specification.html#introspection-format)
defines introspection metadata; semantic explanations are a separate inference.
The [decision-model guidance](https://huggingface.co/blog/ggml-org/decision-models-in-llamacpp)
recommends describing candidate options. Whether these generated descriptions
improve Kev accuracy or latency must still be measured with the actual model.

## Startup comparison

Only hashes of observed schema records persist in
$XDG_CACHE_HOME/aurora-assistant/capability-fingerprints.json (or ~/.cache).
The file contains no transcript, property value, generated explanation or
executable action. It cannot restore capabilities. Added, removed and changed
counts compare bounded observations, not complete desktop inventories.
An incomplete scan can report absent observations for still-running services.
The current session always scans again; preparation and dispatch recheck live
ownership and types. aurora-control catalog-status includes these counts.
