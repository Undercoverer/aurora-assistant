# Optional local search API and spoken summaries

Enable in your existing host configuration:

```nix
programs.aurora-assistant.webSearch = {
  enable = true;
  port = 8888;
  engines = [ "duckduckgo" ];
  maxResults = 5;
  language = "en";
};
```

Rebuild NixOS after updating the Aurora input. The module starts SearXNG through
uWSGI on 127.0.0.1, enables JSON results, and generates a signing key at runtime
outside the Nix store. No public listener or firewall opening is configured.
HTTP access logging is disabled for this managed instance. Ordinary service error
logs and upstream provider logs are outside Aurora's in-memory result handling.
The web feature is disabled by default and is not required for desktop controls.

Examples:

- "Search the web for the latest KDE Plasma release and summarize the changes."
- "Look up how heat pumps work and give a short explanation."
- "Search for the opening hours of the public library in [your town]."

Say the location or other necessary context; the assistant does not infer your
location. When enabled, Kev can route an explicit web query directly to search.
Uncertain information requests still go to the larger planner. The planner forms one query from the original request,
then the controller retrieves at most eight results (five by default) and asks
the local model for a short summary with numbered citations.

## What local means

The API server, planner, summarizer, speech recognition, and speech synthesis run
on your device. A live web search still needs internet access. SearXNG forwards
the query to the configured search providers, which can see the query and the
outbound IP. Do not include private information in a web-search request that you
do not want to send to those providers. This feature is not offline web search.
Desktop queries and actions do not need the search service. A fully offline
knowledge search would need a separately downloaded and indexed document corpus.

## Sources and limitations

This implementation summarizes **search-result snippets**, not full articles.
It does not fetch result URLs, run a browser, execute page scripts, or claim to
have checked a full page. Snippets can be incomplete, stale, or incorrect. A
retrieval timestamp records when Aurora searched, not when a claim was published.
The summarizer is instructed to state gaps and disagreements. Citation IDs are
validated against the returned results; that validation cannot prove the model's
summary is factually correct.

After a response, run:

```sh
aurora-control sources
```

This returns the latest successful search summary, cited source titles, original
URLs, snippets, and retrieval time. Results are held in controller memory, not
written to a search-history file. A new search clears the previous result; a
controller restart loses it. The current overlay displays a short answer, not a
clickable source panel. The spoken answer points to the local source command.

Search snippets go only to a separate tool-free summarization request. They are
never fed back to the desktop planner. The search action must run alone and before
desktop discovery: mixed requests should be asked as separate turns. This prevents
web content from becoming a desktop execution plan. Returned URL schemes are
limited to HTTP/HTTPS; local/credential-bearing URLs are discarded. No result URL
is fetched, so this URL filtering is not a general DNS/SSRF protection mechanism.

## Use an existing local SearXNG instance

```nix
programs.aurora-assistant.webSearch = {
  enable = true;
  manageService = false;
  url = "http://127.0.0.1:8080";
};
```

Your instance must enable `search.formats = [ "html" "json" ];`. With
manageService=false, the engines option does not change the external instance.
Aurora accepts only a literal loopback HTTP address, rejects redirects, ignores
HTTP proxy environment variables, and limits response bytes, result counts, and
time. It sends queries as POST form data, using SearXNG's `/search` JSON API.
The API is not an OpenAI endpoint; local model summarization uses the existing
local OpenAI-compatible planner endpoint.

## Troubleshooting

```sh
systemctl status aurora-search-secret.service searx-init.service uwsgi.service
journalctl -u searx-init.service -u uwsgi.service -b
# This sends a real public search query:
curl --fail -X POST http://127.0.0.1:8888/search -d 'q=KDE Plasma&format=json'
```

A 403 response often means JSON output is disabled. A timeout or empty result can
mean provider blocking, rate limiting, loss of internet, or an unavailable engine.
Aurora reports failure or lack of snippets instead of treating model memory as a
successful web search. Local summarization errors also fail the search response.
Live SearXNG deployment and Nix evaluation still require target-host verification.

API reference: https://docs.searxng.org/dev/search_api.html
