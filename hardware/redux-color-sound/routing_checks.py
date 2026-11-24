"""Independent, format-insensitive checks that routing preserved existing copper."""

from decimal import Decimal
import hashlib
import json
import re

from cad_sexpr import Atom, Node, parse


NUMBER = re.compile(r'[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?$')


def tree(node):
    if isinstance(node, Atom):
        value = node.value
        return str(Decimal(value).normalize()) if NUMBER.fullmatch(value) else value
    return [tree(c) for c in node.children]


def board_records(text):
    root = parse(text)
    net_names = {n.value(): n.value(2) for n in root.nodes('net')}
    copper = {}
    for kind in ('segment', 'via', 'arc'):
        for item in root.nodes(kind):
            record = []
            for child in item.children[1:]:
                if not isinstance(child, Node) or child.name in ('uuid', 'locked', 'status'):
                    continue
                if child.name == 'net':
                    record.append(['net', net_names.get(child.value(), child.value())])
                else:
                    record.append(tree(child))
            # Ordering of fields is not electrical/physical geometry.
            copper[item.one('uuid').value()] = [kind, sorted(record, key=lambda r: r[0])]
    footprints = {}
    for fp in root.nodes('footprint'):
        props = {p.value(): p.value(2) for p in fp.nodes('property')}
        pads = []
        for pad in fp.nodes('pad'):
            record = [c.value for c in pad.children[1:] if isinstance(c, Atom)]
            children = []
            for child in pad.children:
                if isinstance(child, Node) and child.name not in ('uuid', 'net', 'pinfunction', 'pintype'):
                    children.append(tree(child))
            net = pad.nodes('net')
            children.append(['net', net_names.get(net[0].value(), net[0].value()) if net else ''])
            pads.append([record, sorted(children, key=lambda r: r[0])])
        footprints[props['Reference']] = {
            'library': fp.value(), 'value': props['Value'], 'at': tree(fp.one('at')),
            'layer': tree(fp.one('layer')), 'pads': sorted(pads, key=repr),
        }
    return {'copper': copper, 'footprints': footprints}


def records_digest(records):
    data = json.dumps(records, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(data).hexdigest()


def preservation_report(before_text, after_text):
    before, after = board_records(before_text), board_records(after_text)
    removed = sorted(set(before['copper'])-set(after['copper']))
    changed = sorted(key for key in before['copper'] if key in after['copper']
                     and before['copper'][key] != after['copper'][key])
    moved = sorted(ref for ref, old in before['footprints'].items()
                   if after['footprints'].get(ref) != old)
    protected = {key: after['copper'][key] for key in before['copper'] if key in after['copper']}
    return {'protected_copper_count': len(before['copper']),
            'protected_footprint_count': len(before['footprints']),
            'missing_copper': removed, 'changed_copper': changed, 'changed_footprints': moved,
            'before_copper_sha256': records_digest(before['copper']),
            'after_protected_copper_sha256': records_digest(protected),
            'added_copper_count': len(set(after['copper'])-set(before['copper'])),
            'preserved': not (removed or changed or moved)}
