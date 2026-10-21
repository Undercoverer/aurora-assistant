"""Bounded, session-local documentation of interfaces actually observed on D-Bus."""
import copy
import json
import re
import time


def words(text):
    text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)
    return set(re.findall(r'[a-z0-9]+', text.lower()))


class CapabilityCatalog:
    def __init__(self, notes=None, max_age=300):
        self.objects = {}
        self.adapter = None
        self.notes = notes
        self.max_age = max_age
        self.comparison = None

    def advertise(self, snapshot):
        """Replace the live adapter schema atomically; reject malformed metadata."""
        self.adapter = None
        if type(snapshot) is not dict or set(snapshot) != {'source', 'description'}:
            raise ValueError('Invalid capability snapshot')
        source, description = snapshot['source'], snapshot['description']
        if (type(source) is not dict or set(source) != {'bus', 'destination', 'path', 'interface', 'owner'}
                or any(type(v) is not str or not v or len(v) > 512 for v in source.values())
                or type(description) is not dict or type(description.get('version')) is not int
                or description['version'] != 1
                or type(description.get('actions')) is not list or len(description['actions']) > 32
                or len(json.dumps(snapshot).encode()) > 65536):
            raise ValueError('Invalid capability description')
        seen = set()
        for entry in description['actions']:
            if (type(entry) is not dict or set(entry) != {'name', 'description', 'argument'}
                    or type(entry['name']) is not str or not entry['name'] or len(entry['name']) > 128
                    or entry['name'] in seen or type(entry['description']) is not str
                    or len(entry['description']) > 1024 or type(entry['argument']) is not dict):
                raise ValueError('Invalid advertised action schema')
            seen.add(entry['name'])
        self.adapter = (time.monotonic(), copy.deepcopy(snapshot))

    def advertised(self):
        if self.adapter is None or (self.max_age is not None and time.monotonic() - self.adapter[0] > self.max_age):
            return []
        snapshot = self.adapter[1]
        return [{'target': snapshot['source'], 'kind': 'advertised action', 'name': entry['name'],
                 'detail': {'argument': entry['argument']}, 'description': entry['description'],
                 'binding': {'name': entry['name'], 'argument': entry['argument']}}
                for entry in copy.deepcopy(snapshot['description']['actions'])]

    def observe(self, action, value):
        if action.name == 'desktop_read' and action.argument in {'applications', 'themes', 'colors'}:
            if isinstance(value, (dict, list)):
                key = 'desktop:' + action.argument
                self.objects.pop(key, None)
                self.objects[key] = (time.monotonic(), {'topic': action.argument}, copy.deepcopy(value))
                while len(self.objects) > 16:
                    self.objects.pop(next(iter(self.objects)))
            return
        if action.name != 'dbus_inspect' or not isinstance(value, dict):
            return
        endpoint = dict(action.argument)
        key = json.dumps(endpoint, sort_keys=True)
        # A new observation replaces the whole object, including removed members.
        self.objects.pop(key, None)
        if not value.get('interfaces'):
            return  # Empty tree roots must not evict useful member observations.
        self.objects[key] = (time.monotonic(), endpoint, copy.deepcopy(value))
        while len(self.objects) > 16:
            self.objects.pop(next(iter(self.objects)))

    def _observed_documents(self):
        docs = self.advertised()
        now = time.monotonic()
        for observed, endpoint, value in list(self.objects.values()):
            if self.max_age is not None and now - observed > self.max_age:
                continue
            if 'topic' in endpoint:
                topic = endpoint['topic']
                action = {'applications': 'launch_app', 'themes': 'theme', 'colors': 'color_scheme'}[topic]
                for identifier in list(value)[:64]:
                    if not isinstance(identifier, str):
                        continue
                    label = value[identifier] if isinstance(value, dict) else identifier
                    docs.append({'target': endpoint, 'kind': 'desktop', 'name': identifier,
                                 'detail': {'label': label},
                                 'description': f'{action}: {label} (installed ID {identifier})',
                                 'candidate': {'name': action, 'argument': identifier}})
                    if len(docs) == 256:
                        return docs
                continue
            for interface in value.get('interfaces', [])[:32]:
                target = {**endpoint, 'interface': interface['name']}
                for kind, members in (('method', interface.get('methods', [])), ('property', interface.get('properties', []))):
                    for member in members[:64]:
                        name = member['name']
                        detail = {k: v for k, v in member.items() if k != 'name'}
                        document = {'target': target, 'kind': kind, 'name': name, 'detail': detail}
                        if kind == 'method' and member.get('input') == '':
                            document['candidate'] = {'name': 'dbus_call', 'argument': {**target, 'method': name, 'argumentsJson': '[]'}}
                        elif kind == 'property' and member.get('access') in ('read', 'readwrite'):
                            document['candidate'] = {'name': 'dbus_get', 'argument': {**target, 'property': name}}
                        docs.append(document)
                        if len(docs) == 256:
                            return docs
                        if kind == 'property' and member.get('access') == 'readwrite' and member.get('signature') == 'b':
                            for setting in (True, False):
                                docs.append({'target': target, 'kind': 'property', 'name': name, 'detail': detail,
                                             'description': f"Set observed boolean property {target['interface']}.{name} to {setting}",
                                             'candidate': {'name': 'dbus_set', 'argument': {
                                                 **target, 'property': name, 'valueJson': json.dumps(setting)}}})
                                if len(docs) == 256:
                                    return docs
        return docs

    def documents(self):
        docs = self._observed_documents()
        if self.notes is not None:
            for doc in docs:
                note = self.notes.get(doc)
                if note:
                    doc['semantic_note'] = note
        return docs

    def search(self, query, limit=12):
        terms = words(query)
        # A small lexical context supplement for the generative planner.
        docs = self.documents()
        def score(doc):
            return len(terms & words(json.dumps(doc)))
        return sorted(docs, key=score, reverse=True)[:limit]

    def routing_documents(self, query):
        # Stable ordering preserves the cacheable capability prefix and gives
        # synonyms the same available tools. Kev supports 255 choices including
        # the explicit escalation option. Query text never filters capabilities.
        return sorted((d for d in self.documents() if 'candidate' in d or 'binding' in d),
                      key=lambda doc: json.dumps(doc, sort_keys=True))[:254]

    def status(self):
        docs = self.documents()
        return {'live_documents': len(docs),
                'explained_live_documents': sum('semantic_note' in d for d in docs),
                'stored_explanations': len(self.notes.entries) if self.notes is not None else 0,
                'enrichment_enabled': self.notes is not None,
                'snapshot_comparison': self.comparison}

    def markdown(self):
        lines = ['# Observed D-Bus capabilities', '',
                 'Startup observations; calls are rechecked before execution. Signatures do not prove intent or safety.' if self.max_age is None else 'Session cache; expires after five minutes. Signatures do not prove intent or safety.', '']
        for doc in self.documents():
            target = doc['target']
            lines.extend([f"## {doc['kind']}: {doc['name']}", '',
                doc.get('description', ''), '',
                ('Unverified model explanation: ' + json.dumps(doc['semantic_note'], ensure_ascii=True))
                    if 'semantic_note' in doc else '', '',
                '```json', json.dumps({**target, **doc['detail']}, ensure_ascii=True, indent=2), '```', ''])
        return '\n'.join(lines)[:90000]
