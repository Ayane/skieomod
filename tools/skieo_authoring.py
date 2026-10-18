"""Portable authoring sources: visual triggers, resources and object CSV edits.

This module deliberately has no desktop or image-library dependency. All source
formats are compiled by the same build used by the graphical workshop.
"""
from __future__ import annotations
import copy
import csv
import io
import json
import math
from pathlib import Path
import re

if __package__ == 'tools':
    from .custom_maps import safe_relative_path, ManifestError
    from .skieo_game_catalog import CATALOG, DEFAULTS
    from .skieo_scene import compile_scene
else:
    from custom_maps import safe_relative_path, ManifestError
    from skieo_game_catalog import CATALOG, DEFAULTS
    from skieo_scene import compile_scene

EVENTS = ('map.before_load', 'map.after_load', 'map.ready', 'map.terrain_loaded',
          'map.load_failed', 'map.unloading', 'calendar.month_changed',
          'calendar.year_changed', 'weather.changed', 'placeable.built',
          'placeable.removed', 'trail.created', 'trail.removed')
# Input/output types drive graph pins and compiler checking. Data inputs
# require links; literal values belong to constant nodes.
NODES = {
    'entry': {'title': 'Event', 'inputs': {}, 'outputs': {'then': 'exec'}},
    'log': {'title': 'Print message', 'inputs': {'in': 'exec', 'message': 'any'}, 'outputs': {'then': 'exec'}, 'defaults': {'message': 'Welcome to my mountain!'}},
    'funds': {'title': 'Add funds', 'inputs': {'in': 'exec', 'amount': 'number'}, 'outputs': {'then': 'exec'}, 'defaults': {'amount': 1000}},
    'time': {'title': 'Set time rate', 'inputs': {'in': 'exec', 'rate': 'number'}, 'outputs': {'then': 'exec'}, 'defaults': {'rate': 1}},
    'pause': {'title': 'Pause time', 'inputs': {'in': 'exec', 'paused': 'boolean'}, 'outputs': {'then': 'exec'}, 'defaults': {'paused': True}},
    'weather': {'title': 'Force weather', 'inputs': {'in': 'exec', 'weather': 'string'}, 'outputs': {'then': 'exec'}, 'defaults': {'weather': 'Sunny'}},
    'release_weather': {'title': 'Release weather', 'inputs': {'in': 'exec'}, 'outputs': {'then': 'exec'}},
    'status': {'title': 'Set resort status', 'inputs': {'in': 'exec', 'status': 'string'}, 'outputs': {'then': 'exec'}, 'defaults': {'status': 'Open'}},
    'scenario_configure': {'title': 'Configure scenario', 'inputs': {'in': 'exec', 'currency': 'string', 'start_year': 'number', 'starting_balance': 'number', 'ticket_price': 'number'}, 'outputs': {'then': 'exec'}, 'defaults': {'rules_module': ''}},
    'branch': {'title': 'Branch', 'inputs': {'in': 'exec', 'condition': 'boolean'}, 'outputs': {'true': 'exec', 'false': 'exec'}, 'defaults': {'condition': True}},
    'delay': {'title': 'Delay', 'inputs': {'in': 'exec', 'seconds': 'number'}, 'outputs': {'then': 'exec'}, 'defaults': {'seconds': 1}},
    'number': {'title': 'Number', 'inputs': {}, 'outputs': {'value': 'number'}, 'defaults': {'value': 0}},
    'text': {'title': 'Text', 'inputs': {}, 'outputs': {'value': 'string'}, 'defaults': {'value': 'Hello'}},
    'boolean': {'title': 'Boolean', 'inputs': {}, 'outputs': {'value': 'boolean'}, 'defaults': {'value': True}},
    'event_value': {'title': 'Event value', 'inputs': {}, 'outputs': {'value': 'any'}, 'defaults': {'key': 'month', 'fallback': 0}},
    'add': {'title': 'Add', 'inputs': {'a': 'number', 'b': 'number'}, 'outputs': {'value': 'number'}, 'defaults': {'a': 0, 'b': 0}},
    'multiply': {'title': 'Multiply', 'inputs': {'a': 'number', 'b': 'number'}, 'outputs': {'value': 'number'}, 'defaults': {'a': 1, 'b': 1}},
    'compare': {'title': 'Compare', 'inputs': {'a': 'number', 'b': 'number'}, 'outputs': {'value': 'boolean'}, 'defaults': {'a': 0, 'b': 0, 'operator': '>='}},
}
OBJECTS = [
    {'id': 'ticket-office', 'name': 'Ticket Office', 'class': '/Game/Blueprints/Buildings/BP_TicketOffice.BP_TicketOffice_C',
     'fields': {'BaseCost': 'integer', 'IndoorCapacity': 'integer', 'DailyOperatingCost': 'integer', 'OpenHour': 'number', 'CloseHour': 'number', 'bAllowQueueing': 'boolean', 'MeshComponent.StaticMesh': 'model'}},
    {'id': 'chair-lift', 'name': 'Chair lift (one seat)', 'class': '/Game/Blueprints/Lifts/BP_FixedChair1.BP_FixedChair1_C',
     'fields': {'BaseCost': 'integer', 'Capacity': 'integer', 'OperatingSpeed': 'number', 'OpenHour': 'number', 'CloseHour': 'number', 'DefaultLiftPrice': 'integer', 'ChairMesh': 'asset', 'StartTerminalMesh.StaticMesh': 'model', 'EndTerminalMesh.StaticMesh': 'model'}},
    {'id': 'skier', 'name': 'Skier / crowd renderer', 'class': '/Script/SkiResortSimulator.CrowdRenderingActor',
     'fields': {'CrowdISM.StaticMesh': 'asset', 'EquippedISM.StaticMesh': 'asset', 'SnowboardISM.StaticMesh': 'asset'}},
]
CSV_FIELDS = ('object', 'field', 'type', 'value')
GENERATED_SCRIPT = 'Scripts/skieomod-generated-authoring.lua'

# The catalogue covers the game's buildings, lifts, decorations and terrain
# park elements. Shared properties use their actual reflected native types;
# values are read from the installed game's class default objects.
for item in OBJECTS:
    item['kind'] = 'skier' if item['id'] == 'skier' else 'lift' if item['id'] == 'chair-lift' else 'building'
for item in CATALOG:
    if not any(existing['class'] == item['class'] for existing in OBJECTS):
        prototype = OBJECTS[1] if item['kind'] == 'lift' else OBJECTS[0] if item['kind'] in ('building','decoration','park') else None
        OBJECTS.append({**item, 'fields': copy.deepcopy(prototype['fields']) if prototype else {}})
for captured in DEFAULTS['objects']:
    item = next((o for o in OBJECTS if o['class'] == captured['class']), None)
    if item:
        if captured.get('fields'): item['fields'] = copy.deepcopy(captured['fields'])
        if 'placeable' in captured: item['placeable'] = captured['placeable']
for spec in NODES.values():
    spec['defaults'] = {key: value for key, value in spec.get('defaults', {}).items() if key not in spec['inputs']}


def source_path(project, relative):
    path = Path(project) / safe_relative_path(relative, 'authoring source')
    if not path.resolve().is_relative_to(Path(project).resolve()) or path.is_symlink():
        raise ManifestError('Authoring sources must stay inside the project')
    return path


def read_json(project, relative, limit=8 * 1024 * 1024):
    path = source_path(project, relative)
    if path.stat().st_size > limit:
        raise ManifestError('Authoring JSON is too large: ' + relative)
    def reject(value):
        raise ManifestError('Non-finite authoring JSON value: ' + value)
    return json.loads(path.read_text(encoding='utf-8-sig'), parse_constant=reject)


def lua(value):
    if value is None:
        return 'nil'
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            raise ManifestError('Lua literals must be finite')
        return repr(value)
    if isinstance(value, str):
        escaped = ''.join('\\' + char if char in '\\"' else f'\\{ord(char):03d}' if ord(char) < 32 else char for char in value)
        return '"' + escaped + '"'
    if isinstance(value, list):
        return '{' + ','.join(lua(item) for item in value) + '}'
    if isinstance(value, dict):
        return '{' + ','.join('[' + lua(key) + ']=' + lua(item) for key, item in sorted(value.items())) + '}'
    raise ManifestError('Unsupported Lua literal')


def new_trigger(identifier='welcome', name='Welcome message'):
    return {'id': identifier, 'name': name, 'enabled': True, 'event': 'map.ready', 'mode': 'graph',
            'graph': {'nodes': [{'id': 'event', 'kind': 'entry', 'position': [40, 100], 'params': {}},
                                {'id': 'message', 'kind': 'log', 'position': [370, 100], 'params': {}},
                                {'id': 'welcome-text', 'kind': 'text', 'position': [40, 270], 'params': {'value': 'Welcome to my mountain!'}}],
                      'edges': [{'source': 'event', 'port': 'then', 'target': 'message', 'input': 'in'},
                                {'source': 'welcome-text', 'port': 'value', 'target': 'message', 'input': 'message'}]}}


def type_of(value):
    return 'boolean' if isinstance(value, bool) else 'number' if isinstance(value, (float, int)) and math.isfinite(value) else 'string' if isinstance(value, str) else 'invalid'


def compile_graph(graph, *, complete=True):
    if not isinstance(graph, dict) or not isinstance(graph.get('nodes'), list) or not isinstance(graph.get('edges'), list):
        raise ManifestError('A graph requires nodes and edges')
    if len(graph['nodes']) > 512 or len(graph['edges']) > 2048:
        raise ManifestError('Trigger graphs support at most 512 nodes and 2048 links')
    nodes = {}
    for node in graph['nodes']:
        if not isinstance(node, dict) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', str(node.get('id', ''))):
            raise ManifestError('Invalid graph node ID')
        if node['id'] in nodes or node.get('kind') not in NODES or not isinstance(node.get('params', {}), dict):
            raise ManifestError('Duplicate node ID or unknown graph node kind')
        nodes[node['id']] = node
    entries = [n['id'] for n in nodes.values() if n['kind'] == 'entry']
    if len(entries) != 1:
        raise ManifestError('Each graph needs exactly one Event node')
    incoming, outgoing, links = {}, {}, {key: [] for key in nodes}
    for edge in graph['edges']:
        try:
            start, end = nodes[edge['source']], nodes[edge['target']]
            output = NODES[start['kind']]['outputs'][edge['port']]
            input_type = NODES[end['kind']]['inputs'][edge['input']]
        except (KeyError, TypeError) as error:
            raise ManifestError('A graph link names a missing node or pin') from error
        if output != input_type and 'any' not in (output, input_type):
            raise ManifestError('Graph pins have incompatible types')
        if (output == 'exec') != (input_type == 'exec'):
            raise ManifestError('Execution pins cannot connect to data pins')
        key = (edge['target'], edge['input'])
        if key in incoming:
            raise ManifestError('An input pin accepts only one link')
        incoming[key] = edge
        if output == 'exec':
            key = (edge['source'], edge['port'])
            if key in outgoing:
                raise ManifestError('An execution output accepts only one link')
            outgoing[key] = edge['target']
        links[edge['source']].append(edge['target'])
    counts = {key: 0 for key in nodes}
    for children in links.values():
        for child in children: counts[child] += 1
    pending = [key for key in nodes if counts[key] == 0]
    order = []
    while pending:
        key = pending.pop(0);order.append(key)
        for child in links[key]:
            counts[child] -= 1
            if counts[child] == 0: pending.append(child)
    if len(order) != len(nodes):
        raise ManifestError('Graph cycles are forbidden; use an event or a timer')
    if not complete: return ''
    expressions = {}

    def parameter(node, key):
        return node.get('params', {}).get(key, NODES[node['kind']].get('defaults', {}).get(key))
    def value(identifier, pin, expected=None):
        node = nodes[identifier]
        edge = incoming.get((identifier, pin))
        if edge:
            expression = expression_of(edge['source'])
            actual = NODES[nodes[edge['source']]['kind']]['outputs'][edge['port']]
            if actual == 'any' and expected in ('number', 'boolean', 'string'):
                expression = f'_typed({expression}, {lua(expected)})'
            return expression
        if pin in NODES[node['kind']]['inputs']:
            raise ManifestError('Connect a constant or value node to ' + NODES[node['kind']]['title'] + '.' + pin)
        literal = parameter(node, pin)
        wanted = expected or NODES[node['kind']]['inputs'].get(pin, 'any')
        if wanted != 'any' and type_of(literal) != wanted:
            raise ManifestError(f'{NODES[node["kind"]]["title"]}.{pin} needs a {wanted}')
        return lua(literal)
    def expression_of(identifier):
        if identifier in expressions: return expressions[identifier]
        node = nodes[identifier]
        kind = node['kind']
        if kind in ('number', 'boolean', 'text'):
            expected = NODES[kind]['outputs']['value']
            literal = parameter(node, 'value')
            if type_of(literal) != expected:
                raise ManifestError('Invalid constant node value')
            return lua(literal)
        if kind == 'event_value':
            key = parameter(node, 'key')
            if not isinstance(key, str) or len(key) > 128:
                raise ManifestError('Event key must be a short string')
            return f'_event_value(event, {lua(key)}, {lua(parameter(node, "fallback"))})'
        if kind in ('add', 'multiply', 'compare'):
            operator = {'add': '+', 'multiply': '*'}.get(kind, parameter(node, 'operator'))
            if operator not in ('+', '*', '==', '~=', '>', '<', '>=', '<='):
                raise ManifestError('Unknown comparison operator')
            return '(' + value(identifier, 'a', 'number') + ' ' + operator + ' ' + value(identifier, 'b', 'number') + ')'
        raise ManifestError('This node has no value output')
    def flow(identifier, indent='    '):
        if identifier is None: return ''
        if len(indent) > 260: raise ManifestError('At most 64 nested branches or delays are supported')
        node = nodes[identifier]
        kind = node['kind']
        if kind == 'entry': return flow(outgoing.get((identifier, 'then')), indent)
        if kind == 'branch':
            return (indent + 'if ' + value(identifier, 'condition', 'boolean') + ' then\n'
                    + flow(outgoing.get((identifier, 'true')), indent + '    ')
                    + indent + 'else\n' + flow(outgoing.get((identifier, 'false')), indent + '    ') + indent + 'end\n')
        if kind == 'delay':
            return (indent + 'api:after(_delay(' + value(identifier, 'seconds', 'number') + '), function()\n'
                    + flow(outgoing.get((identifier, 'then')), indent + '    ') + indent + 'end)\n')
        calls = {'log': ('api:log', 'message', 'any'), 'funds': ('api.game:add_funds', 'amount', 'number'),
                 'time': ('api.game:set_time_rate', 'rate', 'number'), 'pause': ('api.game:pause_time', 'paused', 'boolean'),
                 'weather': ('api.game:force_weather', 'weather', 'string'), 'status': ('api.game:set_resort_status', 'status', 'string')}
        if kind == 'scenario_configure':
            module = parameter(node, 'rules_module')
            if not isinstance(module, str) or module and not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', module):
                raise ManifestError('Scenario rules module must be a local Lua module name or empty')
            fields = ', '.join(key + ' = ' + value(identifier, key, expected) for key, expected in NODES[kind]['inputs'].items() if expected != 'exec')
            line = 'do\n' + indent + '    local options = {' + fields + '}\n'
            if module:
                line += indent + '    local rules = require(' + lua(module) + ')\n'
                line += indent + '    for _, key in ipairs({"costs", "class_costs", "loans", "track_lift_rides"}) do options[key] = rules[key] end\n'
            line += indent + '    api.game:configure(options)\n' + indent + 'end'
        elif kind == 'release_weather': line = 'api.game:release_weather()'
        elif kind in calls:
            function, argument, expected = calls[kind]
            line = function + '(' + value(identifier, argument, expected) + ')'
        else: raise ManifestError('A data node cannot be in the execution chain')
        return indent + line + '\n' + flow(outgoing.get((identifier, 'then')), indent)
    # Evaluate each data node once, in dependency order. Shared expressions
    # therefore cannot grow exponentially when a graph fans out and rejoins.
    declarations = []
    for identifier in order:
        node = nodes[identifier]
        if 'value' in NODES[node['kind']]['outputs']:
            expression = expression_of(identifier)
            variable = '_v' + str(len(declarations) + 1)
            declarations.append('    local ' + variable + ' = ' + expression + '\n')
            expressions[identifier] = variable
        for pin, wanted in NODES[node['kind']]['inputs'].items():
            if wanted != 'exec': value(identifier, pin, wanted)
    if len(declarations) > 180: raise ManifestError('At most 180 data nodes are supported in one trigger')
    return ''.join(declarations) + flow(entries[0])


def compile_triggers(document, *, before_script=None):
    if not isinstance(document, dict) or document.get('version') != 1 or not isinstance(document.get('triggers'), list):
        raise ManifestError('Trigger sources require version: 1 and a triggers array')
    if len(document['triggers']) > 256:
        raise ManifestError('At most 256 triggers are supported')
    result, identifiers = [], set()
    for trigger in document['triggers']:
        if not isinstance(trigger, dict) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', str(trigger.get('id', ''))):
            raise ManifestError('Invalid trigger ID')
        if trigger['id'] in identifiers or trigger.get('event') not in EVENTS or not isinstance(trigger.get('enabled', True), bool):
            raise ManifestError('Duplicate trigger ID, unknown event or invalid enabled flag')
        identifiers.add(trigger['id'])
        early = trigger.get('before_script', False)
        if not isinstance(early, bool):
            raise ManifestError('Trigger before_script must be a boolean')
        mode = trigger.get('mode', 'graph')
        if mode == 'graph': body = compile_graph(trigger.get('graph'))
        elif mode == 'lua':
            body = trigger.get('lua', '')
            if not isinstance(body, str) or len(body.encode()) > 1024 * 1024:
                raise ManifestError('Trigger Lua must be text of at most 1 MiB')
        else: raise ManifestError('Trigger mode must be graph or lua')
        if trigger.get('enabled', True) and (before_script is None or early == before_script):
            result.append('api:on(' + lua(trigger['event']) + ', function(event)\n' + body + '\nend)')
    return '\n'.join(result)


def parse_obj(data, units='meters', up_axis='z'):
    """Triangulated OBJ in authoring units -> portable centimetre mesh.

    Separate indices are expanded per triangle corner. Materials are supplied
    by the replaced game component, keeping OBJ import independent of a cook.
    """
    if units not in ('meters', 'centimeters') or up_axis not in ('z', 'y'):
        raise ManifestError('OBJ units must be meters/centimeters, up axis z/y')
    if len(data) > 32 * 1024 * 1024:
        raise ManifestError('OBJ files must be at most 32 MiB')
    positions, uv, vertices, triangles, normals, texture = [], [], [], [], [], []
    scale = 100 if units == 'meters' else 1
    def index(token, items):
        value = int(token)
        resolved = value - 1 if value > 0 else len(items) + value
        if value == 0 or resolved < 0 or resolved >= len(items):
            raise ManifestError('OBJ index is out of range')
        return items[resolved]
    try:
        for raw in data.decode('utf-8-sig').splitlines():
            fields = raw.split('#', 1)[0].split()
            if not fields: continue
            if fields[0] == 'v':
                value = [float(v) * scale for v in fields[1:4]]
                if len(value) != 3 or any(not math.isfinite(v) or abs(v) > 1e8 for v in value):
                    raise ManifestError('Invalid OBJ vertex')
                if up_axis == 'y': value = [value[0], -value[2], value[1]]
                positions.append(value)
            elif fields[0] == 'vt':
                value = [float(v) for v in fields[1:3]]
                if len(value) != 2 or any(not math.isfinite(v) for v in value):
                    raise ManifestError('Invalid OBJ texture coordinate')
                uv.append(value)
            elif fields[0] == 'f':
                corners = [part.split('/') for part in fields[1:]]
                if len(corners) < 3 or len(corners) > 128:
                    raise ManifestError('An OBJ face must have 3 to 128 corners')
                for step in range(1, len(corners) - 1):
                    chosen = [corners[0], corners[step], corners[step + 1]]
                    points = [index(corner[0], positions) for corner in chosen]
                    a = [points[1][axis] - points[0][axis] for axis in range(3)]
                    b = [points[2][axis] - points[0][axis] for axis in range(3)]
                    cross = [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]
                    length = math.sqrt(sum(v*v for v in cross))
                    if length < 1e-10: continue
                    normal = [v / length for v in cross]
                    triangles.extend(range(len(vertices), len(vertices) + 3))
                    for point, corner in zip(points, chosen):
                        vertices.append(point); normals.append(normal)
                        texture.append(index(corner[1], uv) if len(corner) > 1 and corner[1] else [0, 0])
                    if len(vertices) > 150000:
                        raise ManifestError('Portable OBJ models support at most 50,000 triangles')
    except (ValueError, IndexError, UnicodeError) as error:
        raise ManifestError('Invalid OBJ geometry: ' + str(error)) from error
    if not triangles:
        raise ManifestError('The OBJ has no non-degenerate faces')
    return {'vertices': vertices, 'triangles': triangles, 'normals': normals, 'uv': texture}


def validate_resources(project, document):
    if not isinstance(document, dict) or document.get('version') != 1 or not isinstance(document.get('assets'), list):
        raise ManifestError('Resource sources require version: 1 and an assets array')
    assets = {}
    for asset in document['assets']:
        if not isinstance(asset, dict) or not re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,79}', str(asset.get('id', ''))):
            raise ManifestError('Invalid resource ID')
        if asset['id'] in assets or asset.get('kind') not in ('model', 'image', 'sound', 'game'):
            raise ManifestError('Duplicate resource ID or invalid resource kind')
        item = copy.deepcopy(asset)
        if asset['kind'] == 'game':
            if not isinstance(asset.get('path'), str) or not re.fullmatch(r'/(?:Game|Engine)/[A-Za-z0-9_/]+\.[A-Za-z0-9_]+', asset['path']):
                raise ManifestError('Game resources require a full /Game/…/Asset.Asset path')
        else:
            path = source_path(project, asset.get('file'))
            if not path.is_file() or path.stat().st_size > 32 * 1024 * 1024:
                raise ManifestError('Resource file is missing or exceeds 32 MiB')
            if asset['kind'] == 'model':
                if path.suffix.lower() != '.obj':
                    raise ManifestError('Portable models use OBJ; cooked game meshes use a game reference')
                item['mesh'] = parse_obj(path.read_bytes(), asset.get('units', 'meters'), asset.get('up_axis', 'z'))
        assets[asset['id']] = item
    if len(assets) > 1024:
        raise ManifestError('At most 1024 authoring resources are supported')
    return assets


def csv_bytes(edits):
    output = io.StringIO(newline='')
    fields = CSV_FIELDS + ('instance',) if any(edit.get('instance') for edit in edits) else CSV_FIELDS
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator='\n')
    writer.writeheader()
    for edit in sorted(edits, key=lambda row: (row['object'], row.get('instance', ''), row['field'])):
        writer.writerow({**edit, 'value': json.dumps(edit['value'], ensure_ascii=False, allow_nan=False)})
    return output.getvalue().encode('utf-8')


def parse_edits(data, resources=None):
    resources = resources or {}
    if len(data) > 4 * 1024 * 1024:
        raise ManifestError('Object CSV must be at most 4 MiB')
    reader = csv.DictReader(io.StringIO(data.decode('utf-8-sig'), newline=''))
    fields = tuple(reader.fieldnames or ())
    if fields not in (CSV_FIELDS, CSV_FIELDS + ('instance',)):
        raise ManifestError('Object CSV columns must be object,field,type,value, with an optional instance column')
    result, seen = [], set()
    for row in reader:
        if set(row) != set(fields) or any(value is None for value in row.values()):
            raise ManifestError('Invalid object CSV row')
        cls = row['object']
        if not re.fullmatch(r'/(?:Game|Script/SkiResortSimulator)/[A-Za-z0-9_/]+\.[A-Za-z0-9_]+', cls) and not re.fullmatch(r'/Script/SkiResortSimulator\.[A-Za-z0-9_]+', cls):
            raise ManifestError('Object overrides require a Ski-E-O class path')
        field = row['field']
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?', field):
            raise ManifestError('Object field must be a property or component.property')
        instance = row.get('instance', '')
        if instance and not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,79}', instance):
            raise ManifestError('Object instance must be a scene object ID')
        key = cls, instance, field
        if key in seen:
            raise ManifestError('Duplicate object override')
        seen.add(key)
        try: value = json.loads(row['value'])
        except ValueError as error: raise ManifestError('CSV values must be JSON literals') from error
        kind = row['type']
        if kind == 'integer': valid = isinstance(value, int) and not isinstance(value, bool) and -2147483648 <= value <= 2147483647
        elif kind == 'number': valid = type_of(value) == 'number' and abs(value) < 1e12
        elif kind == 'boolean': valid = isinstance(value, bool)
        elif kind in ('string', 'name', 'text'): valid = isinstance(value, str) and len(value) <= 4096
        elif kind in ('asset', 'model', 'sound'):
            valid = isinstance(value, str)
            if valid and value.startswith('asset:'):
                asset = resources.get(value[6:])
                valid = asset is not None and (asset['kind'] == 'game' or kind == 'model' and asset['kind'] == 'model')
                if valid and asset['kind'] == 'game': value = asset['path']
            else:
                valid = valid and bool(re.fullmatch(r'/(?:Game|Engine)/[A-Za-z0-9_/]+\.[A-Za-z0-9_]+', value))
            if kind == 'model' and field.endswith('ISM.StaticMesh') and isinstance(value, str) and value.startswith('asset:'):
                valid = False
        else: valid = False
        if not valid:
            raise ManifestError('Unsupported object value/type or resource: ' + field)
        result.append({'object': cls, 'field': field, 'type': kind, 'value': value, **({'instance': instance} if instance else {})})
        if len(result) > 2048:
            raise ManifestError('At most 2048 object overrides are supported')
    return result


def prepare(project, manifest, generated, *, source_build=None):
    """Compile source-only authoring files and embed them after the base script."""
    settings = source_build if source_build is not None else manifest.get('build', {})
    selected = {key: settings[key] for key in ('triggers', 'resources', 'objects', 'scene') if key in settings}
    if not selected: return manifest, []
    inputs, resources, edits, registrations, early_registrations = [], {}, [], '', ''
    for key, setting in selected.items():
        if not isinstance(setting, dict) or set(setting) != {'file'}:
            raise ManifestError('build.' + key + ' requires only a project-relative file')
        inputs.append(str(safe_relative_path(setting['file'], 'build.' + key + '.file')))
    if 'resources' in selected:
        resources = validate_resources(project, read_json(project, selected['resources']['file']))
        inputs.extend(item['file'] for item in resources.values() if 'file' in item)
    if 'triggers' in selected:
        triggers = read_json(project, selected['triggers']['file'])
        early_registrations = compile_triggers(triggers, before_script=True)
        registrations = compile_triggers(triggers, before_script=False)
    if 'objects' in selected:
        edits = parse_edits(source_path(project, selected['objects']['file']).read_bytes(), resources)
    placements = compile_scene(read_json(project, selected['scene']['file']), manifest) if 'scene' in selected else []
    by_id = {item['id']: item for item in placements}
    # A custom scene label belongs to that instance and takes precedence over
    # a map-wide name override for the type.
    if any(edit['field']=='InstanceName' and not edit.get('instance') for edit in edits):
        for item in placements:
            if item['name'] and not any(edit.get('instance')==item['id'] and edit['field']=='InstanceName' for edit in edits):
                edits.append({'object':item['class'],'instance':item['id'],'field':'InstanceName','type':'text','value':item['name']})
    for edit in edits:
        if edit.get('instance'):
            placed = by_id.get(edit['instance'])
            if not placed or placed['class'] != edit['object']:
                raise ManifestError('Object override instance is missing or has a different class: ' + edit['instance'])
            edit['instance'] = placed['guid']
    portable = copy.deepcopy(manifest)
    original = portable.get('script', {})
    entry = original.get('entry')
    if entry == GENERATED_SCRIPT:
        raise ManifestError('The generated authoring script cannot be the source entry point')
    source = generated[entry].decode('utf-8-sig') if entry in generated else source_path(project, entry).read_text(encoding='utf-8-sig') if entry else ''
    meshes = {identifier: asset['mesh'] for identifier, asset in resources.items() if 'mesh' in asset}
    registrations = ('api:on("map.ready", function() api:apply_object_edits(' + lua(edits) + ', ' + lua(meshes) + ') end)\n' if edits else '') + registrations
    if placements: registrations = 'api:on("map.ready", function() api:place_objects(' + lua(placements) + ') end)\n' + registrations
    script = '''-- Generated by skieomod. Edit Triggers/, Resources/ and Objects/ sources.
local original = (function()
''' + source + '''
end)()
local function _typed(value, wanted)
    assert(type(value) == wanted, "Trigger value needs " .. wanted)
    return value
end
local function _event_value(event, key, fallback)
    if type(event) == "table" and event[key] ~= nil then return event[key] end
    return fallback
end
local function _delay(seconds)
    assert(type(seconds) == "number" and seconds >= 0 and seconds <= 86400, "Delay must be within 0..86400 seconds")
    return seconds * 1000
end
local function register(api)
''' + early_registrations + '''
    local base = type(original) == "table" and original.register or original
    if type(base) == "function" then base(api) end
''' + registrations + '''
end
if type(original) == "table" then original.register = register; return original end
assert(original == nil or type(original) == "function", "Invalid map script return value")
return register
'''
    generated[GENERATED_SCRIPT] = script.encode('utf-8')
    portable['script'] = copy.deepcopy(original or {'language': 'lua', 'api': '1.0', 'permissions': []})
    portable['script']['entry'] = GENERATED_SCRIPT
    if 'triggers' in selected and any(
            trigger.get('enabled', True) and trigger.get('mode', 'graph') == 'graph'
            and any(node['kind'] == 'scenario_configure' and node.get('params', {}).get('rules_module')
                    for node in trigger['graph']['nodes']) for trigger in triggers['triggers']):
        # API 1.1 supplies the sandbox's declared local-module importer.
        if portable['script'].get('api', '1.0') == '1.0': portable['script']['api'] = '1.1'
    permissions = portable['script'].setdefault('permissions', [])
    if 'gameplay' not in permissions and 'skieo.unrestricted' not in permissions: permissions.append('gameplay')
    assets = portable['content'].setdefault('assets', [])
    # Generic images/sounds are portable resources. OBJ geometry is embedded in
    # generated Lua, and authoring JSON/CSV must never become runtime sources.
    for asset in resources.values():
        if asset['kind'] in ('image', 'sound') and asset['file'] not in assets: assets.append(asset['file'])
    excluded = {s['file'] for s in selected.values()} | {a['file'] for a in resources.values() if a['kind'] == 'model'}
    portable['content']['assets'] = [p for p in assets if p not in excluded]
    if entry in generated and entry != GENERATED_SCRIPT:
        # The old generated wrapper is already embedded, no duplicate script is
        # needed. Its generated entry is never changed in the source manifest.
        generated.pop(entry)
    portable.pop('build', None)
    return portable, inputs
