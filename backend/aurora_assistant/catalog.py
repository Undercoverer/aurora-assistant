"""Bounded, session-local documentation of interfaces actually observed on D-Bus."""
import copy
import json
import re
import time


def words(text):
    text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)
    return set(re.findall(r'[a-z0-9]+', text.lower()))


class CapabilityCatalog:
    def __init__(self):
        self.objects = {}

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
        self.objects[key] = (time.monotonic(), endpoint, copy.deepcopy(value))
        while len(self.objects) > 16:
            self.objects.pop(next(iter(self.objects)))

    def documents(self):
        docs = []
        now = time.monotonic()
        for observed, endpoint, value in list(self.objects.values()):
            if now - observed > 300:
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

    def search(self, query, limit=12):
        terms = words(query)
        # Cheap lexical retrieval; Kev performs semantic selection over the shortlist.
        docs = self.documents()
        def score(doc):
            return len(terms & words(json.dumps(doc)))
        return sorted(docs, key=score, reverse=True)[:limit]

    def markdown(self):
        lines = ['# Observed D-Bus capabilities', '',
                 'Session cache; expires after five minutes. Signatures do not prove intent or safety.', '']
        for doc in self.documents():
            target = doc['target']
            lines.extend([f"## {doc['kind']}: {doc['name']}", '',
                '```json', json.dumps({**target, **doc['detail']}, ensure_ascii=True, indent=2), '```', ''])
        return '\n'.join(lines)[:90000]
