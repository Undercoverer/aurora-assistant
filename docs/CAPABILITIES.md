# Discovered D-Bus capabilities and Kev

Aurora records interfaces returned by successful `dbus_inspect` actions. Each
method or property becomes a document containing the bus, service, object path,
interface, member, signature, and property access. No service names or signatures
are invented. The cache contains at most 16 objects and exposes at most 256 member
documents; observations expire after five minutes and disappear on restart.
Reinspection replaces the complete object so removed members disappear.

A keyword search, including splitting CamelCase member names, retrieves at most
12 documents. Kev then makes a semantic choice among concrete candidates, with
an explicit escalation option. This is lexical retrieval with model reranking,
not an embedding/vector index. No additional embedding model or service is needed.
The larger planner receives the retrieved documents too.

Kev may select a readable property or a method with no input arguments when one
candidate covers the entire request. A request needing parameters, ambiguous
semantics, multiple generic calls, or further discovery escalates. Kev does not
invent parameter values. Common supported requests have separate fully parsed
candidates, including multi-action requests such as "mute the speakers and pause
playback". A confidence score is not proof of safety: all generic mutations still
pass live introspection, typed validation, service-owner checking, and approval.

The catalog starts empty. Ask a question such as "Inspect the available KWin
interfaces" or make an unfamiliar desktop request to trigger the planner's bounded
discovery. It does not crawl every session/system object at startup. An interface
signature describes types, not meaning, units, valid ranges or side effects; these
may still require upstream documentation or a clarification question.

Export the currently observed documentation while the controller is running:

```sh
aurora-control capabilities > aurora-capabilities.md
```

This uses the same private, same-user control socket as approval. Documents may
contain application/service names. They contain interface metadata, not property
values or microphone recordings. Exports are capped at 90,000 characters. The export is a snapshot, not an executable
configuration file. The live interface is checked again before changes execute.
