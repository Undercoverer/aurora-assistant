# Discovered D-Bus capabilities

The controller reads `org.aurora.Desktop1.Describe` through the local MCP server. This
versioned JSON description comes from the running desktop adapter's unique owner
and advertises operations, descriptions and argument schemas. It is additive to
the desktop service; the pinned overlay API is unchanged.

Default realtime discovery lists currently running session and system services
for each request. It does not crawl all objects at startup or keep a service catalog
across requests. Kev can select an observed service root or child object to inspect;
Qwen can choose further discovery steps or generate arguments when more reasoning
is needed. Selection uses the request and observed data, with no application-category
lookup or special timer/clock discovery logic.

The default MCP discoveryScope is "all": ordinary desktop permissions govern access.
"restricted" applies sessionPrefixes/systemPrefixes. Each list exposes at most 150
services from the server's bounded 512-name response and marks truncation. Missing
services, introspection errors and search-budget exhaustion never prove an application
is absent. Only running services are listed; discovery does not activate applications.

At most four reads are proposed per planning round; settings.maxRounds defaults to
five. Individual MCP calls and the entire request have timeouts. The planner follows
observed child paths on demand and can read current properties. Reinspection replaces
old members. Every mutation is still prepared against a fresh schema and service owner.
The retained startup/periodic modes are explicit legacy choices; scanMaxObjects applies
to those modes, not a crawl before a realtime request.

Native introspection supplies bus, service, path, interface, member, signature and
access. Application/theme/color reads supply installed IDs. Native observations
retain at most 16 objects; the combined catalog exposes at most 256 documents.
All observations are planning hints. In the explicit startup mode they remain
for the session; realtime mode replaces them each turn.
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
