#!/usr/bin/env python3
"""Compare paused scenario checkpoints before/after a save or reload."""
import argparse
import json
import math
from pathlib import Path


def differences(before, after, snow_tolerance=0.5):
    failures = []
    for report in (before, after):
        if report.get('engine_paused') is not True:
            failures.append(f"{report.get('label', '?')}: engine was not paused")
        for loan in report.get('loans', []):
            if not isinstance(loan, dict) or any(key not in loan for key in ('tier', 'principal', 'remaining', 'monthly_rate', 'months')):
                failures.append('loans: missing contract measurements')
    for field in ('map_id', 'map_version', 'calendar', 'weather', 'debt', 'ticket_price', 'script_state', 'loans'):
        if field not in before or field not in after:
            failures.append(f'{field}: missing measurement')
        elif before[field] != after[field]:
            failures.append(f'{field}: changed')
    def indexed(report):
        lifts = report.get('lifts', [])
        result = {lift['id']: lift for lift in lifts}
        if not lifts or len(result) != len(lifts):
            failures.append('lifts: missing measurements or duplicate identifiers')
        return result
    first, second = indexed(before), indexed(after)
    if first.keys() != second.keys():
        failures.append('lifts: identifiers changed')
    for identifier in first.keys() & second.keys():
        a, b = first[identifier], second[identifier]
        for key in ('name', 'running', 'skiing', 'status', 'rides', 'staff'):
            if key not in a or key not in b or a[key] != b[key]:
                failures.append(f'lift {identifier}: {key} changed or missing')
        for terminal in ('bottom_snow', 'top_snow'):
            for component in ('packed_cm', 'fresh_cm', 'total_cm'):
                x, y = (a.get(terminal) or {}).get(component), (b.get(terminal) or {}).get(component)
                if not isinstance(x, (int, float)) or not isinstance(y, (int, float)) or not math.isfinite(x) or not math.isfinite(y) or abs(x-y) > snow_tolerance:
                    failures.append(f'lift {identifier}: {terminal}.{component} changed or missing')
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('before', type=Path)
    parser.add_argument('after', type=Path)
    parser.add_argument('--snow-tolerance-cm', type=float, default=0.5)
    args = parser.parse_args()
    if not 0 <= args.snow_tolerance_cm <= 1:
        parser.error('snow tolerance must be between 0 and 1 cm')
    failures = differences(json.loads(args.before.read_text()), json.loads(args.after.read_text()), args.snow_tolerance_cm)
    if failures:
        print('\n'.join(failures))
        return 1
    print('OK: paused calendar, finances, script state, lifts and snow are stable')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
