#!/usr/bin/env python3
"""Turn buildings/data/buildings.csv into buildings/data/buildings.geojson.

The CSV is the list you edit by hand:

    address,year,description,osm
    "Галицька, 1",1933,Житловий будинок,
    "Мельничука, 14",1842,Будинок повітового старости,way/205674030

For every row the script finds the matching building in OpenStreetMap by its
address (street + house number). The optional `osm` column pins a row to a
specific OSM object (`way/123` or `relation/123`); use it when the address
can't be found or matches the wrong building, e.g. after a street rename.

It then writes the current OSM outline of each building, with your year and
description, to buildings.geojson, which the map draws. Never edit that file
by hand: change the CSV and run the script again (also to pick up OSM edits).

Usage:
    python tools/build_buildings.py                       # fetch OSM data and build
    python tools/build_buildings.py --save-osm osm.json   # also keep the download
    python tools/build_buildings.py --osm-file osm.json   # reuse a download
"""
import argparse
import csv
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / 'buildings' / 'data' / 'buildings.csv'
GEOJSON_PATH = ROOT / 'buildings' / 'data' / 'buildings.geojson'

# Same area as the map's maxBounds (south, west, north, east).
BBOX = (48.8778, 24.6189, 48.9913, 24.814)
OVERPASS_URLS = [
    'https://overpass-api.de/api/interpreter',
    'https://overpass.kumi.systems/api/interpreter',
]
USER_AGENT = 'map.klym.uk buildings build script'

# Street-type words and their canonical form.
STREET_TYPES = {
    'вулиця': 'вулиця', 'вул': 'вулиця',
    'площа': 'площа', 'пл': 'площа',
    'майдан': 'майдан',
    'провулок': 'провулок', 'пров': 'провулок',
    'бульвар': 'бульвар', 'бул': 'бульвар',
    'проспект': 'проспект', 'просп': 'проспект',
    'набережна': 'набережна',
    'тупик': 'тупик',
    'проїзд': 'проїзд',
    'алея': 'алея',
}


def norm_street(name):
    """'Галицька вулиця' / 'вулиця Галицька' / 'Галицька' -> ('вулиця', ('галицька',))."""
    s = name.lower().replace('’', "'").replace('ʼ', "'").replace('`', "'")
    tokens = [t for t in re.split(r"[\s.,]+", s) if t]
    kind = 'вулиця'
    rest = []
    for t in tokens:
        if t in STREET_TYPES:
            kind = STREET_TYPES[t]
        else:
            rest.append(t)
    return kind, tuple(rest)


LATIN_TO_CYR = str.maketrans('abcehkmoptx', 'авсенкмортх')   # Latin look-alikes


def norm_number(num):
    """'12-А' / '12а' / '12 a' -> '12а'. Ranges like '7-9' are kept."""
    s = num.strip().lower().translate(LATIN_TO_CYR)
    s = re.sub(r'(\d)\s*[-‐–]?\s*([^\d\s/;,\-])', r'\1\2', s)
    return re.sub(r'\s+', '', s)


def split_numbers(value):
    return [norm_number(p) for p in re.split(r'[;,]', value) if p.strip()]


def fetch_osm(save_to=None):
    s, w, n, e = BBOX
    bbox = f'({s},{w},{n},{e})'
    query = (f'[out:json][timeout:180];'
             f'(way[building]{bbox};relation[building]{bbox};);out geom;'
             # Street relations: many buildings here carry only a house number
             # and get their street name from one of these.
             f'(relation[type=associatedStreet]{bbox};relation[type=street]{bbox};);out body;')
    body = urllib.parse.urlencode({'data': query}).encode()
    last_error = None
    for attempt in range(4):
        url = OVERPASS_URLS[attempt % len(OVERPASS_URLS)]
        try:
            req = urllib.request.Request(url, data=body, headers={'User-Agent': USER_AGENT})
            with urllib.request.urlopen(req, timeout=240) as resp:
                raw = resp.read()
            data = json.loads(raw)
            if save_to:
                Path(save_to).write_bytes(raw)
            return data
        except Exception as ex:  # busy server, timeout, HTML error page...
            last_error = ex
            print(f'  Overpass request failed ({url}): {ex}; retrying...', file=sys.stderr)
            time.sleep(10 * (attempt + 1))
    sys.exit(f'Could not download OSM data: {last_error}')


# ---- Geometry ----

def ring_area(points):
    """Approximate area in m² of a closed ring of {'lat','lon'} points."""
    if len(points) < 4 or points[0] != points[-1]:
        return 0.0
    kx, ky = 111320.0 * 0.6578, 111320.0      # metres per degree at 48.9°N
    a = 0.0
    for p, q in zip(points, points[1:]):
        a += p['lon'] * kx * q['lat'] * ky - q['lon'] * kx * p['lat'] * ky
    return abs(a) / 2


def _pt(p):
    return [round(p['lon'], 7), round(p['lat'], 7)]


def _stitch(lines):
    """Join way pieces that share end points into closed rings."""
    lines = [list(l) for l in lines if len(l) >= 2]
    rings = []
    while lines:
        ring = lines.pop(0)
        while ring[0] != ring[-1]:
            for i, l in enumerate(lines):
                if l[0] == ring[-1]:
                    ring = ring + l[1:]
                elif l[-1] == ring[-1]:
                    ring = ring + l[::-1][1:]
                elif l[-1] == ring[0]:
                    ring = l[:-1] + ring
                elif l[0] == ring[0]:
                    ring = l[::-1][:-1] + ring
                else:
                    continue
                lines.pop(i)
                break
            else:
                break                     # can't close it (a member is missing)
        if ring[0] == ring[-1] and len(ring) >= 4:
            rings.append(ring)
    return rings


def _inside(pt, ring):
    x, y, c = pt[0], pt[1], False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            c = not c
    return c


def geometry(el):
    """GeoJSON geometry of a building way or multipolygon relation."""
    if el['type'] == 'way':
        ring = [_pt(p) for p in el.get('geometry', [])]
        return {'type': 'Polygon', 'coordinates': [ring]} if len(ring) >= 4 and ring[0] == ring[-1] else None
    members = [m for m in el.get('members', []) if m['type'] == 'way' and m.get('geometry')]
    outers = _stitch([[_pt(p) for p in m['geometry']] for m in members if m.get('role') != 'inner'])
    inners = _stitch([[_pt(p) for p in m['geometry']] for m in members if m.get('role') == 'inner'])
    polys = [[o] for o in outers]
    for inner in inners:                  # courtyards
        for poly in polys:
            if _inside(inner[0], poly[0]):
                poly.append(inner)
                break
    if not polys:
        return None
    if len(polys) == 1:
        return {'type': 'Polygon', 'coordinates': polys[0]}
    return {'type': 'MultiPolygon', 'coordinates': polys}


# ---- Address lookup ----

def build_index(osm):
    """Returns (street key, number) -> refs, all street keys, ref -> area, ref -> element."""
    street_of = {}                  # building ref -> street name from a street relation
    for el in osm['elements']:
        if el['type'] == 'relation' and el.get('tags', {}).get('type') in ('associatedStreet', 'street'):
            name = el['tags'].get('name')
            for m in el.get('members', []) if name else []:
                if m.get('role') == 'house':
                    street_of[f"{m['type']}/{m['ref']}"] = name
    index = defaultdict(list)
    streets = set()
    area = {}
    elements = {}
    for el in osm['elements']:
        tags = el.get('tags', {})
        if 'building' not in tags:
            continue
        ref = f"{el['type']}/{el['id']}"
        elements[ref] = el
        if el['type'] == 'way':
            area[ref] = ring_area(el.get('geometry', []))
        else:
            area[ref] = sum(ring_area(m.get('geometry', [])) for m in el.get('members', []) if m.get('role') == 'outer')
        street = tags.get('addr:street') or street_of.get(ref)
        numbers = tags.get('addr:housenumber')
        if not street or not numbers:
            continue
        key = norm_street(street)
        streets.add(key)
        for num in split_numbers(numbers):
            index[(key, num)].append(ref)
    return index, streets, area, elements


def find_street(key, streets):
    """Exact street match, else a unique OSM street ending with the same words
    ('Труша' -> 'вулиця Івана Труша')."""
    if key in streets:
        return key
    kind, words = key
    matches = [s for s in streets if s[0] == kind and s[1][-len(words):] == words]
    return matches[0] if len(matches) == 1 else None


def resolve(address, index, streets, area):
    """Returns (ref, error, note)."""
    m = re.match(r'^\s*(.+?)\s*,\s*(.+?)\s*$', address)
    if not m:
        return None, 'address must look like "Street, number"', None
    street = find_street(norm_street(m.group(1)), streets)
    if not street:
        return None, 'street not found in OSM', None
    number = norm_number(m.group(2))
    refs = index.get((street, number), [])
    if not refs and re.match(r'^\d+[^\d]?-\d+', number):          # '7-9' -> try '7'
        refs = index.get((street, number.split('-')[0]), [])
    if not refs:
        return None, 'house number not found on this street in OSM', None
    if len(refs) > 1:
        # Usually a main house plus courtyard buildings: take the largest.
        refs = sorted(set(refs), key=lambda r: -area.get(r, 0))
        return refs[0], None, (f'{len(refs)} OSM buildings have this address; using the largest, {refs[0]} '
                               f'(others: {", ".join(refs[1:])})')
    return refs[0], None, None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--osm-file', help='use a saved Overpass response instead of downloading')
    ap.add_argument('--save-osm', help='save the Overpass response to this file')
    args = ap.parse_args()

    if args.osm_file:
        osm = json.loads(Path(args.osm_file).read_text(encoding='utf-8'))
    else:
        print('Downloading OSM buildings...')
        osm = fetch_osm(args.save_osm)
    index, streets, area, elements = build_index(osm)

    rows = list(csv.DictReader(CSV_PATH.open(encoding='utf-8-sig', newline='')))
    features, problems, notes, used = [], [], [], {}
    for line, row in enumerate(rows, start=2):           # line 1 is the header
        address = (row.get('address') or '').strip()
        pinned = (row.get('osm') or '').strip()
        try:
            year = int(row['year'])
        except (KeyError, ValueError):
            problems.append((line, address, f"year '{row.get('year')}' is not a number"))
            continue
        if pinned:
            if not re.match(r'^(way|relation)/\d+$', pinned):
                problems.append((line, address, f"osm '{pinned}' must look like way/123 or relation/123"))
                continue
            if pinned not in elements:
                problems.append((line, address, f'{pinned} is not a building in OSM (deleted, or a building:part?)'))
                continue
            ref = pinned
        else:
            ref, err, note = resolve(address, index, streets, area)
            if err:
                problems.append((line, address, err))
                continue
            if note:
                notes.append((line, address, note))
        if ref in used:
            problems.append((line, address, f'same OSM building ({ref}) as line {used[ref]}; this row is skipped'))
            continue
        geom = geometry(elements[ref])
        if not geom:
            problems.append((line, address, f'{ref} has no usable outline in OSM'))
            continue
        used[ref] = line
        features.append({
            'type': 'Feature',
            'id': len(features) + 1,
            'properties': {
                'street': address,
                'year': year,
                'description': (row.get('description') or '').strip(),
                'osm': ref,
            },
            'geometry': geom,
        })

    collection = {
        'type': 'FeatureCollection',
        'generated': date.today().isoformat(),
        'osm_timestamp': osm.get('osm3s', {}).get('timestamp_osm_base'),
        'features': features,
    }
    GEOJSON_PATH.write_text(json.dumps(collection, ensure_ascii=False, separators=(',', ':')) + '\n',
                            encoding='utf-8')

    print(f'{len(features)} of {len(rows)} rows matched to OSM buildings -> {GEOJSON_PATH.relative_to(ROOT)}')
    if notes:
        print(f'\n{len(notes)} notes (fine unless the wrong building lights up; then set the osm column):')
        for line, address, msg in notes:
            print(f'  line {line}: {address}: {msg}')
    if problems:
        print(f'\n{len(problems)} rows need attention ({CSV_PATH.relative_to(ROOT)}):')
        for line, address, msg in problems:
            print(f'  line {line}: {address}: {msg}')
        sys.exit(1)


if __name__ == '__main__':
    main()
