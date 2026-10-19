"""Opt-in local SearXNG client. Only snippets are retrieved, never result URLs."""
import asyncio
from datetime import datetime, timezone
from html.parser import HTMLParser
import ipaddress
import json
from urllib.parse import urlsplit
import httpx
from .config import local_url


class Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
    def handle_data(self, value):
        self.parts.append(value)


def clean(value, limit):
    parser = Text()
    parser.feed(str(value)[:limit * 4])
    return ' '.join(' '.join(parser.parts).split())[:limit]


def public_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        return None
    try:
        u = urlsplit(value)
        if u.scheme not in {'http', 'https'} or not u.hostname or u.username or u.password:
            return None
        if any(ord(c) < 33 for c in value):
            return None
        host = u.hostname.lower()
        if host == 'localhost' or host.endswith(('.localhost', '.local', '.internal')):
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            if '.' not in host:
                return None
        return value
    except ValueError:
        return None


class WebSearch:
    def __init__(self, config, transport=None):
        self.config = config
        self.transport = transport

    async def search(self, query):
        if not self.config.get('enable', False):
            raise ValueError('Web search is disabled')
        if not isinstance(query, str) or not query.strip() or len(query) > 512:
            raise ValueError('Search query must contain 1 to 512 characters')
        url = local_url(self.config['url']) + '/search'
        maximum = self.config.get('maxResults', 5)
        if type(maximum) is not int or not 1 <= maximum <= 8:
            raise ValueError('Invalid result limit')
        async with asyncio.timeout(25):
            async with httpx.AsyncClient(transport=self.transport, trust_env=False, follow_redirects=False, timeout=20) as client:
                async with client.stream('POST', url, data={'q': query, 'format': 'json',
                        'language': self.config.get('language', 'en'), 'safesearch': '1'}) as response:
                    response.raise_for_status()
                    if 'application/json' not in response.headers.get('content-type', ''):
                        raise ValueError('Search API did not return JSON; enable its JSON format')
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > 1048576:
                            raise ValueError('Search response exceeded one MiB')
        document = json.loads(data)
        if type(document) is not dict or type(document.get('results')) is not list:
            raise ValueError('Invalid search response')
        results, seen = [], set()
        for item in document['results']:
            if type(item) is not dict:
                continue
            link = public_url(item.get('url'))
            if not link or link in seen:
                continue
            snippet = clean(item.get('content', ''), 1500)
            if not snippet:
                continue
            seen.add(link)
            results.append({'id': len(results) + 1, 'title': clean(item.get('title', ''), 200),
                            'url': link, 'snippet': snippet,
                            'published': clean(item.get('publishedDate') or '', 80)})
            if len(results) >= maximum:
                break
        return {'retrievedAt': datetime.now(timezone.utc).isoformat(), 'results': results,
                'basis': 'Search result snippets only; full pages were not fetched.'}
