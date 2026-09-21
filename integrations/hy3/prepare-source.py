#!/usr/bin/env python3
"""Apply the bounded lifetime fix to build copies of pinned hy3 sources."""
from pathlib import Path
import sys

source, output = map(Path, sys.argv[1:])
output.mkdir(parents=True, exist_ok=True)
layout = (source / 'src/Hy3Layout.cpp').read_text()
node = (source / 'src/Hy3Node.cpp').read_text()


def replace(text, old, new):
    if text.count(old) != 1:
        raise SystemExit('Pinned hy3 source changed; review the lifetime patch: ' + old[:100])
    return text.replace(old, new)


layout = '#include "HyprflipSafety.hpp"\n' + layout
for signature in (
    'void Hy3Layout::insertNode(UP<Hy3Node> node_up, std::optional<Vector2D> focalPoint) {',
    'void Hy3Layout::recalcGeometry(bool no_animation) {',
    'Hy3Node* Hy3Layout::getNodeFromWindow(const CWindow* window) {',
    'Hy3Node* Hy3Layout::getNodeFromTarget(SP<Layout::ITarget> target) {',
):
    layout = replace(layout, signature, signature + '\n\thyprflipPruneExpiredTargets(this->root.get());')
layout = replace(layout, 'if (node->is_target() && node->as_target() == target)',
                 'if (node->is_target() && node->valid() && node->as_target() == target)')
node = replace(node, 'co_yield *this->as_window();',
               'if (this->valid()) {\n\t\t\tif (auto window = this->as_window()) co_yield *window;\n\t\t}')
for name, content in (('Hy3Layout.cpp', layout), ('Hy3Node.cpp', node)):
    target = output / name
    if not target.exists() or target.read_text() != content:
        target.write_text(content)
