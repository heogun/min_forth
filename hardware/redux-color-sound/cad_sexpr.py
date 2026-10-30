"""Small span-preserving reader for KiCad S-expressions (no reformatting)."""

from dataclasses import dataclass
import json
import re


TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|[()]|[^\s()"]+')


@dataclass
class Atom:
    value: str
    start: int
    end: int


@dataclass
class Node:
    children: list
    start: int
    end: int

    @property
    def name(self):
        return self.children[0].value

    def nodes(self, name):
        return [c for c in self.children if isinstance(c, Node) and c.name == name]

    def one(self, name):
        matches = self.nodes(name)
        if len(matches) != 1:
            raise ValueError(f'Expected one {name} in {self.name}, got {len(matches)}')
        return matches[0]

    def value(self, index=1):
        return self.children[index].value

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk()


def parse(text):
    stack = []
    root = None
    for match in TOKEN.finditer(text):
        token = match.group()
        if token == '(':
            node = Node([], match.start(), -1)
            if stack:
                stack[-1].children.append(node)
            elif root is not None:
                raise ValueError('Multiple roots')
            else:
                root = node
            stack.append(node)
        elif token == ')':
            if not stack:
                raise ValueError('Unbalanced closing parenthesis')
            stack.pop().end = match.end()
        else:
            if not stack:
                raise ValueError('Atom outside root')
            value = json.loads(token, strict=False) if token.startswith('"') else token
            stack[-1].children.append(Atom(value, match.start(), match.end()))
    if stack or root is None:
        raise ValueError('Incomplete S-expression')
    return root


def replace(text, edits):
    """Apply non-overlapping (start, end, replacement) edits to original spans."""
    boundary = len(text)
    for start, end, replacement in sorted(edits, reverse=True):
        if not 0 <= start <= end <= boundary:
            raise ValueError('Overlapping or invalid edits')
        text = text[:start] + replacement + text[end:]
        boundary = start
    return text


def quoted(atom, value):
    return atom.start, atom.end, json.dumps(value, ensure_ascii=False)
