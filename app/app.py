#!/usr/bin/env python3
"""Inwentarz Gdański 1531–1591 — przeglądarka zapisek i indeksu.

Uruchomienie:
    .venv-app/bin/python app/app.py           # http://127.0.0.1:5057
    DANZIGER_DB=... DANZINGER_SCANS=... .venv-app/bin/python app/app.py
"""
import math
import os
import re
import sqlite3
import unicodedata
from pathlib import Path
from urllib.parse import urlencode

from flask import Flask, abort, g, redirect, render_template, request, send_file, url_for

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
DB_PATH = Path(os.environ.get('DANZINGER_DB', ROOT / 'data' / 'DANZIGER_INVENTAR_1531-1591' / 'db' / 'danziger_inventar.db'))
SCANS_DIR = Path(os.environ.get('DANZINGER_SCANS', ROOT / 'sources' / 'DANZIGER_INVENTAR_1531-1591' / 'png'))
PAGE_SIZE = 25
MAX_SCAN_PAGE = 1086

app = Flask(__name__)
app.config['DATABASE'] = DB_PATH


def fold(text):
    text = (text or '').translate(str.maketrans({'ł': 'l', 'Ł': 'L', 'ß': 'ss', 'ß': 'ss'}))
    return ''.join(c for c in unicodedata.normalize('NFD', text) if not unicodedata.combining(c))


def fts_query(query, mode):
    if mode == 'fts':
        return query
    if mode == 'phrase':
        q = query.replace('"', '""').strip()
        return f'"{q}"' if q else ''
    terms = []
    for phrase, word in re.findall(r'"([^"]+)"|(\S+)', query):
        term = phrase or word
        prefix = term.endswith('*')
        term = term[:-1] if prefix else term
        term = fold(term).replace('"', '""')
        if term:
            terms.append('"' + term + '"' + ('*' if prefix else ''))
    return ' AND '.join(terms)


def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(f'file:{app.config["DATABASE"]}?mode=ro', uri=True)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA query_only=ON')
    return g.db


@app.teardown_appcontext
def close_db(_):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def page_args():
    try:
        page = int(request.args.get('page', '1'))
    except ValueError:
        page = 1
    return max(1, page)


def page_numbers(current, total):
    lo, hi = max(1, current - 2), min(total, current + 2)
    return range(lo, hi + 1)


def query_inventory():
    args = request.args
    q = (args.get('q') or '').strip()
    mode = args.get('mode', 'words')
    if mode not in ('words', 'phrase', 'fts'):
        mode = 'words'
    year_from = args.get('year_from', '').strip()
    year_to = args.get('year_to', '').strip()
    place = (args.get('place') or '').strip()
    sort = args.get('sort', 'relevance' if q else 'chron')
    if sort not in ('chron', 'relevance'):
        sort = 'relevance' if q else 'chron'

    conditions, params, join = [], [], ''
    order = 'e.iso_date, e.id'
    if q:
        fq = fts_query(q, mode)
        if fq:
            join = 'JOIN inventory_fts ON inventory_fts.rowid = e.id'
            conditions.append('inventory_fts MATCH ?')
            params.append(fq)
            if sort == 'relevance':
                order = 'bm25(inventory_fts)'
    if year_from:
        try:
            yf = int(year_from)
            conditions.append("CAST(substr(e.iso_date,1,4) AS INTEGER) >= ?"); params.append(yf)
        except ValueError:
            pass
    if year_to:
        try:
            yt = int(year_to)
            conditions.append("CAST(substr(e.iso_date,1,4) AS INTEGER) <= ?"); params.append(yt)
        except ValueError:
            pass
    if place:
        needle = fold(place).casefold()
        conditions.append("(lower(e.place) LIKE ? ESCAPE '\\' OR lower(e.place_pl) LIKE ? ESCAPE '\\' OR lower(coalesce(e.place,'')) LIKE ? ESCAPE '\\')")
        like = '%' + needle.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        params.extend([like, like, like])
    where = ('WHERE ' + ' AND '.join(conditions)) if conditions else ''
    return q, mode, year_from, year_to, place, sort, join, where, params, order


@app.route('/')
def home():
    return redirect(url_for('inventory'))


@app.route('/inwentarz')
def inventory():
    db = get_db()
    q, mode, year_from, year_to, place, sort, join, where, params, order = query_inventory()
    page = page_args()
    total = db.execute(f'SELECT count(*) FROM inventory_entry e {join} {where}', params).fetchone()[0]
    pages = max(1, math.ceil(total / PAGE_SIZE))
    page = min(page, pages)
    rows = db.execute(
        f'SELECT e.id, e.entry_number, e.iso_date, e.place, e.place_pl, e.text, e.text_pl, e.is_footnote\n'
        f'FROM inventory_entry e {join} {where}\n'
        f'ORDER BY {order}\nLIMIT ? OFFSET ?',
        [*params, PAGE_SIZE, (page - 1) * PAGE_SIZE]).fetchall()
    row_ids = [r['id'] for r in rows]
    scan_pages = {rid: [] for rid in row_ids}
    if row_ids:
        ph = ','.join('?' * len(row_ids))
        for rid, pg in db.execute(f'SELECT entry_id, page FROM inventory_page WHERE entry_id IN ({ph}) ORDER BY page', row_ids):
            scan_pages[rid].append(pg)
    def url(page_num=None, **kw):
        base = {'q': q, 'mode': mode, 'year_from': year_from, 'year_to': year_to, 'place': place, 'sort': sort}
        if page_num is not None:
            base['page'] = page_num
        base.update(kw)
        return url_for('inventory', **{k: v for k, v in base.items() if v not in ('', None)})
    total_all = db.execute('SELECT count(*) FROM inventory_entry').fetchone()[0]
    return render_template('inventory.html', rows=rows, scan_pages=scan_pages, q=q, mode=mode,
                           year_from=year_from, year_to=year_to, place=place, sort=sort,
                           page=page, pages=pages, total=total, total_all=total_all,
                           page_numbers=page_numbers(page, pages), page_url=url)


@app.route('/inwentarz/<int:entry_id>')
def inventory_entry(entry_id):
    db = get_db()
    e = db.execute('SELECT * FROM inventory_entry WHERE id = ?', (entry_id,)).fetchone()
    if not e:
        abort(404)
    pages = [r[0] for r in db.execute('SELECT page FROM inventory_page WHERE entry_id = ? ORDER BY page', (entry_id,))]
    numbers = [r[0] for r in db.execute('SELECT number FROM inventory_entry_number WHERE entry_id = ? ORDER BY number', (entry_id,))]
    linked = db.execute('''SELECT DISTINCT i.id, i.name, i.description
                           FROM index_entry_number n JOIN index_entry i ON i.id = n.index_id
                           WHERE n.number IN (SELECT number FROM inventory_entry_number WHERE entry_id = ?)
                           ORDER BY i.name COLLATE NOCASE LIMIT 200''', (entry_id,)).fetchall()
    prev_id, next_id = db.execute('SELECT (SELECT MAX(id) FROM inventory_entry WHERE id < ?1), (SELECT MIN(id) FROM inventory_entry WHERE id > ?1)', (entry_id,)).fetchone()
    return render_template('inventory_detail.html', e=e, pages=pages, numbers=numbers, linked=linked,
                           prev_id=prev_id, next_id=next_id)


@app.route('/indeks')
def index_list():
    db = get_db()
    q = (request.args.get('q') or '').strip()
    mode = request.args.get('mode', 'words')
    if mode not in ('words', 'phrase', 'fts'):
        mode = 'words'
    letter = (request.args.get('letter') or '').strip().upper()[:1]
    only_refs = request.args.get('numbered') == '1'
    page = page_args()

    conditions, params, join = [], [], ''
    if q:
        fq = fts_query(q, mode)
        if fq:
            join = 'JOIN index_fts ON index_fts.rowid = i.id'
            conditions.append('index_fts MATCH ?')
            params.append(fq)
    if letter:
        conditions.append('upper(substr(i.name, 1, 1)) = ?')
        params.append(letter)
    if only_refs:
        conditions.append('EXISTS (SELECT 1 FROM index_entry_number n WHERE n.index_id = i.id)')
    where = ('WHERE ' + ' AND '.join(conditions)) if conditions else ''
    total = db.execute(f'SELECT count(*) FROM index_entry i {join} {where}', params).fetchone()[0]
    pages = max(1, math.ceil(total / PAGE_SIZE))
    page = min(page, pages)
    rows = db.execute(
        f'''SELECT i.id, i.name, i.description, i.see,
                   (SELECT count(*) FROM index_entry_number n WHERE n.index_id = i.id) AS n_numbers,
                   (SELECT count(*) FROM index_entry_appendix a WHERE a.index_id = i.id) AS n_appendix
            FROM index_entry i {join} {where}
            ORDER BY i.name COLLATE NOCASE, i.id
            LIMIT ? OFFSET ?''',
        [*params, PAGE_SIZE, (page - 1) * PAGE_SIZE]).fetchall()
    # liczba zapisek przypadająca na hasło (dla listy) złożona w jednym zapytaniu
    def url(page_num=None, **kw):
        base = {'q': q, 'mode': mode, 'letter': letter, 'numbered': '1' if only_refs else ''}
        if page_num is not None:
            base['page'] = page_num
        base.update(kw)
        return url_for('index_list', **{k: v for k, v in base.items() if v not in ('', None, False)})
    total_all = db.execute('SELECT count(*) FROM index_entry').fetchone()[0]
    letters = [chr(c) for c in range(ord('A'), ord('Z') + 1)]
    return render_template('index_list.html', rows=rows, q=q, mode=mode, letter=letter,
                           only_refs=only_refs, page=page, pages=pages, total=total, total_all=total_all,
                           page_numbers=page_numbers(page, pages), page_url=url, letters=letters)


@app.route('/indeks/<int:entry_id>')
def index_detail(entry_id):
    db = get_db()
    e = db.execute('SELECT * FROM index_entry WHERE id = ?', (entry_id,)).fetchone()
    if not e:
        abort(404)
    numbers = [r[0] for r in db.execute('SELECT number FROM index_entry_number WHERE index_id = ? ORDER BY number', (entry_id,))]
    appendix = [r[0] for r in db.execute('SELECT page FROM index_entry_appendix WHERE index_id = ? ORDER BY page', (entry_id,))]
    linked = {}
    if numbers:
        placeholders = ','.join('?' * len(numbers))
        rows = db.execute(f'SELECT DISTINCT en.number, e.id AS entry_id FROM inventory_entry_number en JOIN inventory_entry e ON e.id = en.entry_id WHERE en.number IN ({placeholders})', numbers).fetchall()
        for number, eid in rows:
            linked.setdefault(number, []).append(eid)
    prev_id, next_id = db.execute('SELECT (SELECT MAX(id) FROM index_entry WHERE id < ?1), (SELECT MIN(id) FROM index_entry WHERE id > ?1)', (entry_id,)).fetchone()
    return render_template('index_detail.html', e=e, numbers=numbers, appendix=appendix,
                           linked=linked, prev_id=prev_id, next_id=next_id)


@app.route('/skan/<int:page>')
def scan(page):
    if page < 1 or page > MAX_SCAN_PAGE:
        abort(404)
    path = SCANS_DIR / f'page_{page:04d}.png'
    if not path.is_file():
        abort(404)
    return send_file(path, mimetype='image/png', conditional=True, max_age=86400)


@app.errorhandler(404)
def not_found(_):
    return render_template('404.html'), 404


if __name__ == '__main__':
    if not app.config['DATABASE'].exists():
        raise SystemExit(f'Brak bazy: {app.config["DATABASE"]}')
    app.run(host='127.0.0.1', port=int(os.environ.get('PORT', '5057')), debug=False)
