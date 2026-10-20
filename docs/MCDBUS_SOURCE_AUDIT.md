# mcdbus source audit and Stage 1 prerequisite

Inspected release: mcdbus 2026.3.6.3, PyPI wheel SHA256
`cab7ac96b4b1bfac25b441de7efe43a4c3b393971c9fe65053999624e5395d93`.
Source: https://pypi.org/project/mcdbus/2026.3.6.3/
The wheel contains inspectable Python source; its hash was verified before inspection.

## Findings that change the migration

| Guide assumption | Installed source | Consequence |
| --- | --- | --- |
| Introspection owns call types | `_interaction.call_method` accepts `signature` from the caller, without introspection | The unmodified server does not meet the guide's server-selection rule |
| Introspection returns XML | `_discovery.introspect` returns Markdown | Do not feed its result into an XML parser |
| Unique-owner addressing can preserve approval | `_bus.validate_bus_name` rejects names starting with `:` | A pre-call owner check alone cannot prevent dispatch to a replacement |
| Missing confirmation denies | `_confirm_or_abort` catches errors, and can proceed with warning; notification RuntimeError/TimeoutError also proceeds | Strict behavior must be enforced in code, not assumed from notification configuration |
| Session mutations have a second gate | Session method calls never invoke confirmation | Properties and methods have different guarantees |
| Arbitrary compound values are converted | Only top-level variants are wrapped | Nested `a{sv}` requires additional conversion |
| Audit logs are metadata only | Property values and remote error bodies can reach stderr | Do not forward upstream mutation/error logging into Aurora diagnostics |

The guide must not be implemented literally against this release. Merely adding
an MCP transport would retain caller-owned typing and weaken owner binding.

## Separate experimental server

`mcp/aurora_mcdbus.py` is a strict entry point using mcdbus's BusManager,
dbus-fast's type verifier and FastMCP. It does not register upstream shortcuts
or unrestricted interaction tools. This adaptation is Aurora-maintained code;
it is not a claim that upstream mcdbus already provides these guarantees.
Upstreaming these changes or selecting a server that provides them remains preferable
before deleting Aurora's working execution backend.

Three tools are exposed:

- `describe_object(bus, service, object_path)` returns bounded raw XML and its unique owner.
- `call_method(..., expected_owner, args)` derives the signature from live XML; args is a JSON array string.
- `set_property(..., expected_owner, expected_value, value)` derives the property type and requires readable/writable access, a precondition and readback.

Both mutation tools require elicitation on both buses. Decline, missing support,
malformed confirmation, timeout and disconnect deny. There is no notification or
warning fallback, regardless of environment variables. After confirmation, owner
and selected schema are checked again and invocation targets the unique owner.
These checks do not prove intent or eliminate a property's read-check-write race;
only a service offering atomic compare-and-set can do that. Failed/cancelled calls
may already have changed state. Never retry mutations automatically.

The server caps concurrent tool work at four and accepted calls at 120 per minute.
XML is capped at 128 KiB, argument JSON at 16 KiB, D-Bus calls at eight seconds and
confirmation at sixty seconds. It rejects duplicate JSON keys, non-finite numbers,
file descriptors and implicit variants. JSON dictionaries require string keys.
Descriptions and replies remain untrusted data, not policy instructions.

`mcp.call.duration` and `mcp.call.outcome` are emitted on stderr for admitted calls,
without arguments, property values or remote errors. Rate-limit refusals happen
before admission. Third-party exception logging is suppressed by the stdio entry
point. Aurora turn correlation and stable application error mapping remain client
integration work.

## Nix and rollout

`nix build .#mcdbus` builds the experimental `aurora-mcdbus` executable. FastMCP and
dbus-fast come from the locked nixpkgs; only the missing mcdbus wheel is pinned
separately. The assistant does not install, start or select this server by default.
No runtime pip/uvx/model download is required by this package.

This is the server prerequisite within Stage 1, not completed execution migration.
Aurora still uses its existing backend. The next change must connect the MCP
client, bind each elicitation to exact approved call content, preserve plan expiry,
and add the system-bus second prompt. Do not expose this raw tool surface directly
to a planner without Aurora's policy gate. Discovery migration, semantic retrieval,
reranking and argument routing remain later stages.

## Verification

The baseline backend suite ran locally: 197 tests, no failures, three live-bus tests
skipped. Python 3.12 was used for this local run; CI uses the project's Python 3.11.
The sandbox prohibits D-Bus socket creation. Dedicated CI runs a private test bus
with an exported fixture, never a real desktop service. Local protocol/type tests
use in-memory MCP transport; check CI for the live result at the exact PR head.
Nix evaluation/build and KDE hardware acceptance remain unverified.

```sh
PYTHONPATH=mcp python -m unittest discover -s tests/mcp -v
AURORA_MCP_TEST_BUS=1 PYTHONPATH=mcp dbus-run-session -- python -m unittest discover -s tests/mcp -v
```
