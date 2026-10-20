"""Argument domains derived from advertised schemas, never from request wording."""
import json


def finite_values(schema):
    """Return a bounded discrete domain, or None when generation is required."""
    if type(schema) is not dict:
        return None
    if 'const' in schema:
        values = [schema['const']]
    elif type(schema.get('enum')) is list:
        values = schema['enum']
    elif schema.get('type') == 'boolean':
        values = [False, True]
    elif schema.get('type') == 'integer':
        low, high = schema.get('minimum'), schema.get('maximum')
        if type(low) is not int or type(high) is not int or not 0 <= high - low < 128:
            return None
        values = list(range(low, high + 1))
    else:
        return None
    if not 1 <= len(values) <= 128:
        return None
    # Scalars only. Complex arrays/objects must be generated and validated.
    if any(type(v) not in (str, bool, int) or len(json.dumps(v)) > 512 for v in values):
        return None
    encoded = [json.dumps(v) for v in values]
    if len(set(encoded)) != len(encoded):
        return None
    return values
