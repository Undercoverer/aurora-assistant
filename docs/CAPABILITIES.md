# Discovered D-Bus capabilities

The controller reads `org.aurora.Desktop1.Describe` over the session bus. This
versioned JSON description comes from the running desktop adapter's unique owner
and advertises operations, descriptions and argument schemas. It is additive to
the desktop service; the pinned overlay API is unchanged.

Read-only background discovery lists running services and follows observed child
paths. Each sweep attempts at most 24 objects, considers at most 12 services per
bus, and has a six-second budget. It runs every four minutes. Coverage is partial;
the planner can inspect additional objects on demand. Generic discovery follows
bus policy and is disabled when settings support is disabled.

Native introspection supplies bus, service, path, interface, member, signature and
access. Application/theme/color reads supply installed IDs. Native observations
retain at most 16 objects; the combined catalog exposes at most 256 documents.
Entries expire after five minutes and are replaced on reinspection. Adapter
metadata is refreshed before planning and cleared on refresh failure.

Kev receives up to 254 stably sorted documents, independent of user wording.
Large menus can use interface-group selection before operation selection.
Readable properties, no-input methods and writable boolean properties supply
concrete candidates. Adapter schemas supply finite argument domains. Free-form
arguments and multiple actions go to Qwen. See the [workflow](DECISION_WORKFLOW.md).

The planner additionally receives a small lexical shortlist. There is no embedding
service. Signatures alone do not establish meaning, units, ranges or side effects.
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
