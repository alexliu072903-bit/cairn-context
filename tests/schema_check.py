"""A small JSON Schema subset checker so the published schemas are exercised without extra packages.

Supports: type, enum, const, required, properties, items, pattern, and local $ref into $defs.
"""

import re

TYPES = {
    "string": str,
    "boolean": bool,
    "object": dict,
    "array": list,
    "null": type(None),
}


def type_matches(value, name):
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, TYPES[name])


def check(value, schema, root, path="$"):
    """Return a list of problems; empty when the value satisfies the schema."""
    problems = []
    if "$ref" in schema:
        node = root
        for part in schema["$ref"].lstrip("#/").split("/"):
            node = node[part]
        return check(value, node, root, path)
    if "const" in schema and value != schema["const"]:
        problems.append("%s: expected %r" % (path, schema["const"]))
    if "enum" in schema and value not in schema["enum"]:
        problems.append("%s: %r is not one of %r" % (path, value, schema["enum"]))
    if "type" in schema:
        names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(type_matches(value, n) for n in names):
            return problems + ["%s: expected type %s" % (path, "/".join(names))]
    if "pattern" in schema and isinstance(value, str) and not re.search(schema["pattern"], value):
        problems.append("%s: %r does not match %s" % (path, value, schema["pattern"]))
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                problems.append("%s: missing %r" % (path, key))
        for key, sub in schema.get("properties", {}).items():
            if key in value:
                problems += check(value[key], sub, root, "%s.%s" % (path, key))
    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            problems += check(item, schema["items"], root, "%s[%d]" % (path, index))
    return problems
