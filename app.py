#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ArcoIris Nav — 原导航页视觉 + 可视化管理后台
单文件 Flask 应用：SQLite 存服务列表，/admin 增删改，/ 保持原页面样式
"""
import os
import sqlite3
import time
import secrets
import urllib.request
import socket
from functools import wraps
from flask import (Flask, request, jsonify, render_template,
                   session, redirect, url_for, abort, send_from_directory)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get('DATA_DIR', '/data')
DB_PATH = os.path.join(DATA_DIR, 'services.db')
UPLOAD_DIR = os.path.join(DATA_DIR, 'uploads')
ALLOWED_ICON_EXT = {'.png', '.jpg', '.jpeg', '.svg', '.ico', '.webp', '.gif'}
MAX_ICON_BYTES = 2 * 1024 * 1024
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', '123456')
PORT = int(os.environ.get('PORT', 8081))

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__, static_folder='static', template_folder='templates',
            static_url_path='')
app.secret_key = os.environ.get('SECRET_KEY') or os.urandom(32).hex()

# ---------------- 数据库 ----------------

SEED = [
    ('飞牛 NAS',   'http://192.168.5.105:5666/',      '#3385ff', 'server'),
    ('kikoeru',    'http://192.168.5.105:8888/',      '#af00ff', 'headphones'),
    ('Komga',      'http://192.168.5.105:25600/',     '#2ed000', 'book'),
    ('哔哩哔哩',    'https://www.bilibili.com/',        '#09c5de', 'tv'),
    ('Emby',       'http://192.168.5.105:8096/',      '#da5b5b', 'film'),
    ('Calibre',    'http://192.168.5.105:8083/',      '#d4a40a', 'book-open'),
    ('Homarr',     'http://192.168.5.105:7575/',      '#444444', 'grid'),
]


# 页面文案默认值（可在管理后台修改）
DEFAULT_SETTINGS = {
    'poem_en_1': "Shall I compare thee to a summer's day?",
    'poem_cn_1': "我可否将你比作一个夏日",
    'poem_en_2': "Thou art more lovely and more temperate.",
    'poem_cn_2': "你比夏天还要美丽温婉",
    'signature': "他山之石，可以攻玉",
}


def db():
    con = sqlite3.connect(DB_PATH, timeout=8)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = db()
    try:
        con.execute("""
            CREATE TABLE IF NOT EXISTS services (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                name    TEXT    NOT NULL,
                url     TEXT    NOT NULL,
                color   TEXT    DEFAULT '#3385ff',
                icon    TEXT    DEFAULT '',
                sort    INTEGER DEFAULT 0,
                enabled INTEGER DEFAULT 1
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT ''
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS groups (
                id   INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT    NOT NULL,
                sort INTEGER DEFAULT 0
            )
        """)
        # 兼容旧库：services 表补 group_id 列（NULL = 未分组）
        cols = [r[1] for r in con.execute("PRAGMA table_info(services)")]
        if 'group_id' not in cols:
            con.execute("ALTER TABLE services ADD COLUMN group_id INTEGER")
        for k, v in DEFAULT_SETTINGS.items():
            con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
        con.commit()
        if con.execute("SELECT COUNT(*) FROM services").fetchone()[0] == 0:
            for i, (n, u, c, ic) in enumerate(SEED):
                con.execute(
                    "INSERT INTO services(name,url,color,icon,sort) VALUES(?,?,?,?,?)",
                    (n, u, c, ic, i * 10))
            con.commit()
    except sqlite3.IntegrityError:
        # 多 worker 并发初始化时忽略重复插入
        con.rollback()
    finally:
        con.close()


def get_settings():
    con = db()
    try:
        rows = con.execute("SELECT key, value FROM settings").fetchall()
    finally:
        con.close()
    d = dict(DEFAULT_SETTINGS)
    d.update({r['key']: r['value'] for r in rows})
    return d


# ---------------- 认证 ----------------

def login_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if not session.get('ok'):
            return redirect(url_for('login', next=request.path))
        return f(*a, **kw)
    return wrapper


@app.route('/login', methods=['GET', 'POST'])
def login():
    err = None
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['ok'] = True
            nxt = request.args.get('next') or url_for('admin')
            return redirect(nxt)
        err = '密码错误'
        time.sleep(0.6)
    return render_template('login.html', err=err)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


# ---------------- 前台 ----------------

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/services')
def api_list():
    con = db()
    rows = con.execute(
        "SELECT * FROM services WHERE enabled=1 ORDER BY sort, id").fetchall()
    con.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/settings')
def api_settings():
    return jsonify(get_settings())


# ---------------- 分组 / 前台拖拽落库 ----------------

def _edit_ok():
    """轻量写保护：必须带自定义请求头（避免地址栏误触/表单提交）。
    内网自用导航页，不做登录校验 —— 但 8889 不要暴露到公网。"""
    return request.headers.get('X-Nav-Edit') == '1'


@app.route('/api/groups', methods=['GET', 'POST'])
def api_groups():
    if request.method == 'GET':
        con = db()
        rows = con.execute("SELECT * FROM groups ORDER BY sort, id").fetchall()
        con.close()
        return jsonify([dict(r) for r in rows])

    if not _edit_ok():
        return jsonify({'error': 'forbidden'}), 403
    name = ((request.get_json(force=True) or {}).get('name') or '').strip()
    if not name:
        return jsonify({'error': '分组名称必填'}), 400
    con = db()
    try:
        mx = con.execute("SELECT COALESCE(MAX(sort),0) FROM groups").fetchone()[0]
        cur = con.execute("INSERT INTO groups(name,sort) VALUES(?,?)", (name[:40], mx + 10))
        con.commit()
        gid = cur.lastrowid
    finally:
        con.close()
    return jsonify({'id': gid, 'name': name[:40]}), 201


@app.route('/api/groups/<int:gid>', methods=['PUT', 'DELETE'])
def api_group_item(gid):
    if not _edit_ok():
        return jsonify({'error': 'forbidden'}), 403
    con = db()
    try:
        if request.method == 'DELETE':
            con.execute("UPDATE services SET group_id=NULL WHERE group_id=?", (gid,))
            con.execute("DELETE FROM groups WHERE id=?", (gid,))
        else:
            d = request.get_json(force=True) or {}
            if 'name' in d:
                nm = (d.get('name') or '').strip()[:40]
                if nm:
                    con.execute("UPDATE groups SET name=? WHERE id=?", (nm, gid))
            if 'sort' in d:
                con.execute("UPDATE groups SET sort=? WHERE id=?", (int(d['sort']), gid))
        con.commit()
    finally:
        con.close()
    return jsonify({'ok': True})


@app.route('/api/layout', methods=['POST'])
def api_layout():
    """前台拖拽后落库：批量写入 [{id, group_id, sort}]"""
    if not _edit_ok():
        return jsonify({'error': 'forbidden'}), 403
    items = (request.get_json(force=True) or {}).get('items') or []
    con = db()
    try:
        for it in items:
            try:
                sid = int(it.get('id'))
            except (TypeError, ValueError):
                continue
            gid = it.get('group_id')
            try:
                gid = int(gid) if gid not in (None, '', 0, '0') else None
            except (TypeError, ValueError):
                gid = None
            con.execute("UPDATE services SET group_id=?, sort=? WHERE id=?",
                        (gid, int(it.get('sort') or 0), sid))
        con.commit()
    finally:
        con.close()
    return jsonify({'ok': True})


# ---------------- 管理后台 ----------------

@app.route('/admin')
@login_required
def admin():
    return render_template('admin.html')


@app.route('/api/admin/services')
@login_required
def api_admin_list():
    con = db()
    rows = con.execute("SELECT * FROM services ORDER BY sort, id").fetchall()
    con.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/admin/services', methods=['POST'])
@login_required
def api_create():
    d = request.get_json(force=True) or {}
    name = (d.get('name') or '').strip()
    url = (d.get('url') or '').strip()
    if not name or not url:
        return jsonify({'error': '名称和地址必填'}), 400
    con = db()
    mx = con.execute("SELECT COALESCE(MAX(sort),0) FROM services").fetchone()[0]
    gid = d.get('group_id')
    try:
        gid = int(gid) if gid not in (None, '', 0, '0') else None
    except (TypeError, ValueError):
        gid = None
    cur = con.execute(
        "INSERT INTO services(name,url,color,icon,sort,enabled,group_id) VALUES(?,?,?,?,?,1,?)",
        (name, url, d.get('color') or '#3385ff', d.get('icon') or '', mx + 10, gid))
    con.commit()
    sid = cur.lastrowid
    con.close()
    return jsonify({'id': sid}), 201


@app.route('/api/admin/services/<int:sid>', methods=['PUT'])
@login_required
def api_update(sid):
    d = request.get_json(force=True) or {}
    fields, vals = [], []
    for k in ('name', 'url', 'color', 'icon'):
        if k in d:
            fields.append(f"{k}=?")
            vals.append(d[k])
    if 'group_id' in d:
        gid = d.get('group_id')
        try:
            gid = int(gid) if gid not in (None, '', 0, '0') else None
        except (TypeError, ValueError):
            gid = None
        fields.append("group_id=?")
        vals.append(gid)
    if 'enabled' in d:
        fields.append("enabled=?")
        vals.append(1 if d['enabled'] else 0)
    if not fields:
        return jsonify({'error': '无可更新字段'}), 400
    vals.append(sid)
    con = db()
    con.execute(f"UPDATE services SET {','.join(fields)} WHERE id=?", vals)
    con.commit()
    con.close()
    return jsonify({'ok': True})


@app.route('/api/admin/services/<int:sid>', methods=['DELETE'])
@login_required
def api_delete(sid):
    con = db()
    con.execute("DELETE FROM services WHERE id=?", (sid,))
    con.commit()
    con.close()
    return jsonify({'ok': True})


@app.route('/api/admin/reorder', methods=['POST'])
@login_required
def api_reorder():
    ids = (request.get_json(force=True) or {}).get('ids') or []
    con = db()
    for i, sid in enumerate(ids):
        con.execute("UPDATE services SET sort=? WHERE id=?", (i * 10, sid))
    con.commit()
    con.close()
    return jsonify({'ok': True})


@app.route('/api/admin/settings', methods=['PUT'])
@login_required
def api_admin_settings():
    data = request.get_json(force=True) or {}
    con = db()
    for k in DEFAULT_SETTINGS:
        if k in data:
            con.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (k, str(data[k])[:500]))
    con.commit()
    con.close()
    return jsonify({'ok': True})


# ---------------- 图标上传 ----------------

@app.route('/uploads/<path:name>')
def uploaded_file(name):
    return send_from_directory(UPLOAD_DIR, name)


@app.route('/api/admin/upload-icon', methods=['POST'])
@login_required
def api_upload_icon():
    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'error': '没有选择文件'}), 400
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ALLOWED_ICON_EXT:
        return jsonify({'error': '仅支持 png / jpg / svg / ico / webp / gif'}), 400

    data = f.read(MAX_ICON_BYTES + 1)
    if len(data) > MAX_ICON_BYTES:
        return jsonify({'error': '文件超过 2MB'}), 400

    name = secrets.token_hex(10) + ext
    with open(os.path.join(UPLOAD_DIR, name), 'wb') as fp:
        fp.write(data)
    return jsonify({'url': '/uploads/' + name})


@app.route('/api/admin/probe-icon')
@login_required
def api_probe_icon():
    """探测目标站点的图标地址：先试 /favicon.ico，再解析首页 <link rel="icon">"""
    target = (request.args.get('url') or '').strip()
    if not target:
        return jsonify({'url': ''})
    return jsonify({'url': _find_favicon(target)})


def _looks_like_image(url, headers):
    try:
        req = urllib.request.Request(url, method='HEAD', headers=headers)
        with urllib.request.urlopen(req, timeout=3) as r:
            if r.status != 200:
                return False
            ct = (r.headers.get('Content-Type') or '').lower()
            if 'image' in ct or 'icon' in ct:
                return True
        # HEAD 返回 octet-stream 时，取前几字节判断魔数
        req2 = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req2, timeout=3) as r2:
            head = r2.read(8)
        return (head[:4] == b'\x00\x00\x01\x00'          # ico
                or head[:4] == b'\x89PNG'                 # png
                or head[:3] == b'GIF'                     # gif
                or head[:2] == b'\xff\xd8')               # jpg
    except Exception:
        return False


def _find_favicon(target):
    import re
    from urllib.parse import urlparse, urljoin

    p = urlparse(target)
    if p.scheme not in ('http', 'https') or not p.netloc:
        return ''
    base = f'{p.scheme}://{p.netloc}'
    ua = {'User-Agent': 'Mozilla/5.0 (compatible; ArcoIrisNav/1.0)'}

    # 1. 约定位置
    cand = base + '/favicon.ico'
    if _looks_like_image(cand, ua):
        return cand

    # 2. 解析首页里的 <link rel="icon">
    try:
        req = urllib.request.Request(base + '/', headers=ua)
        with urllib.request.urlopen(req, timeout=4) as r:
            html = r.read(300000).decode('utf-8', 'ignore')
        patterns = [
            r'<link[^>]+rel=["\'][^"\']*icon[^"\']*["\'][^>]*href=["\']([^"\']+)["\']',
            r'<link[^>]+href=["\']([^"\']+)["\'][^>]*rel=["\'][^"\']*icon[^"\']*["\']',
        ]
        for pat in patterns:
            m = re.search(pat, html, re.I)
            if m:
                found = urljoin(base + '/', m.group(1))
                if _looks_like_image(found, ua):
                    return found
    except Exception:
        pass

    return ''


# ---------------- 在线状态探测 ----------------

@app.route('/api/status')
def api_status():
    """批量探测服务是否可连通（TCP 连接测试，2 秒超时）"""
    con = db()
    rows = con.execute(
        "SELECT id,url FROM services WHERE enabled=1").fetchall()
    con.close()
    out = {}
    for r in rows:
        url = r['url']
        try:
            host, port = _parse_host_port(url)
            s = socket.create_connection((host, port), timeout=2)
            s.close()
            out[r['id']] = True
        except Exception:
            out[r['id']] = False
    return jsonify(out)


def _parse_host_port(url):
    from urllib.parse import urlparse
    p = urlparse(url)
    host = p.hostname or '127.0.0.1'
    if p.port:
        port = p.port
    else:
        port = 443 if p.scheme == 'https' else 80
    return host, port


@app.route('/healthz')
def healthz():
    return 'ok'


# 模块加载时初始化数据库（gunicorn 通过 import 加载，不会走 __main__）
init_db()


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT, threaded=True)
