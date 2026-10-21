# Optional offline recall and evaluation

Embedding recall is disabled by default. It supplements Qwen's existing lexical
evidence with observed records only. It does not change Kev routing, infer action
arguments, grant consent, or bypass deterministic policy. At least half of each
shortlist comes from lexical order. At most 256 observed records are available,
and maxDocuments (64 by default) bounds the lexical-ranked embedding pool.
This limit can miss semantically relevant records outside that pool; evaluate it.

Configure a named repository containing a self-contained BERT-style ONNX encoder
and tokenizers JSON. Use the pooling and query prefix specified by that model.
There is no implicit model choice and no runtime download. Explicit provisioning
resolves revision to one commit, copies only the requested graph/tokenizer, validates
an actual encoder call, and records hashes in the existing model manifest.
External ONNX weight files and remote model code are not supported.

The NixOS options are under programs.aurora-assistant.retrieval:
enable, model, revision, onnxFile, tokenizerFile, modelDirectory, pooling,
queryPrefix, maxTokens, maxDocuments, threads and timeoutSeconds.
Missing assets fail startup. Invalid graphs/tokenizers fail provisioning or startup.
The separate local worker loads once. Request timeout or cancellation terminates it;
later requests use lexical evidence until controller restart. Failure does not
grant any desktop permission. The worker receives text through stdin, not argv.
Normal operation remains offline.

## Run on the target CPU

Export bounded observations:

    aurora-control capability-records > catalog.json

The export can be truncated; check its truncated field before evaluation. Create
a JSON array of labeled cases: each object has query and expected (a list of
document IDs). IDs are SHA256 of the canonical bounded document text computed by
aurora_assistant.recall.document_id. Use representative paraphrases, ambiguous
requests, multiple-action requests and unrelated queries. Empty expected lists
identify unrelated queries. Labels must refer to actual corpus records.

Save the retrieval runtime settings in model-config.json, including the explicit
model name and absolute local directory, then run:

    aurora-evaluate-recall --catalog catalog.json --cases cases.json --model-config model-config.json --k 12 --repeats 5 > recall-results.json

Omit model-config for a lexical baseline. Reports include corpus/case/model hashes,
machine/Python information, sample counts, recall@k, negative queries receiving
candidates, first-request time and p50/p95. First-request timing includes encoder
loading and document encoding; subsequent cache state depends on case order.
These are recall measurements, not wake-to-response latency, calibrated
confidence, action accuracy or a no-match decision. No acceptance threshold is
preselected. Record model configuration, target CPU and representative workload
alongside the JSON. Synthetic unit-test graphs are not accuracy evidence.

Cross-encoder selection, calibrated abstention, selected-schema generation and
replacement of Kev remain gated on measured accuracy/ambiguity and target-CPU
latency. Keep the current route until that evidence supports a separate change.
