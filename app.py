from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, Response
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3, os, secrets, json, re
from datetime import datetime
from functools import wraps
from jinja2 import DictLoader

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None
    dict_row = None

app = Flask(__name__, static_folder=None)
app.secret_key = os.environ.get("SECRET_KEY", "CHANGE_ME_BEFORE_DEPLOY")
DB = os.path.join(os.path.dirname(__file__), "budgetku.db")
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()


# Embedded templates/assets so the project can be uploaded to GitHub from iPhone without preserving folders.
TEMPLATES = {'accounts.html': '{% extends "base.html" %}{% block content %}<div class="form-card"><h1>Rekening & E-wallet</h1><p class="muted">Saldo bersama yang terlihat oleh seluruh perangkat akun keluarga.</p>{% for a in accounts %}<div class="mini" style="margin-bottom:9px"><div class="label">{{a.type}}</div><div class="num">{{a.name}}</div><div class="muted">{{a.balance|rupiah}}</div></div>{% endfor %}<h2>Tambah Rekening</h2><form method="post" style="padding:0;border:0;box-shadow:none"><div class="field"><label>Nama</label><input name="name" required></div><div class="field"><label>Jenis</label><select name="type"><option>Bank</option><option>E-wallet</option><option>Cash</option></select></div><div class="field"><label>Saldo Awal</label><input type="number" name="balance" value="0" min="0"></div><button class="btn">Tambah</button></form></div>{% endblock %}', 'base.html': '<!doctype html><html lang="id"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>BudgetKu</title><link rel="stylesheet" href="{{url_for(\'static\',filename=\'style.css\')}}"></head><body>\n{% if session.get(\'family_id\') %}\n<nav class="nav"><a class="brand" href="{{url_for(\'dashboard\')}}">BudgetKu 💰</a><div class="navlinks"><a href="{{url_for(\'dashboard\')}}">Home</a><a href="{{url_for(\'transaction\')}}">Transaksi</a><a href="{{url_for(\'budgets_page\')}}">Budget</a><a href="{{url_for(\'share\')}}">👥 Share</a><a href="{{url_for(\'logout\')}}">Keluar</a></div></nav>\n{% endif %}\n<div class="container">{% with ms=get_flashed_messages(with_categories=true) %}{% for cat,msg in ms %}<div class="flash">{{msg}}</div>{% endfor %}{% endwith %}{% block content %}{% endblock %}</div>\n</body></html>', 'budgets.html': '{% extends "base.html" %}{% block content %}<div class="form-card"><h1>Atur Budget</h1><p class="muted">Format BudgetKu tetap per rekening dan kategori.</p><form method="post"><div class="field"><label>Bulan</label><input type="month" name="month" value="{{month}}"></div><div class="field"><label>Rekening</label><select name="account_id">{% for a in accounts %}<option value="{{a.id}}">{{a.name}}</option>{% endfor %}</select></div><div class="field"><label>Kategori</label><select name="category_id">{% for c in categories %}<option value="{{c.id}}">{{c.icon}} {{c.name}}</option>{% endfor %}</select></div><div class="field"><label>Budget per bulan</label><input type="number" name="amount" min="0" required></div><button class="btn">Simpan Budget</button></form></div>{% endblock %}', 'dashboard.html': '{% extends "base.html" %}{% block content %}\n<section class="hero-card">\n<div class="logo">BudgetKu 💰</div>\n<div class="tagline">Keuangan keluarga, lebih rapi, terarah, dan terkontrol. 💙💗</div>\n<div class="statsline">{{accounts|length}} akun · {{tx_count}} transaksi</div>\n<div class="bigmoney">{{total|rupiah}}</div>\n<div class="actions">\n<a class="action blue" href="{{url_for(\'transaction\')}}?kind=expense">+ Pengeluaran</a>\n<a class="action pink" href="{{url_for(\'transaction\')}}?kind=income">+ Pemasukan</a>\n<a class="action light wide" href="{{url_for(\'accounts_page\')}}">💰 Atur Saldo Awal Rekening & E-wallet</a>\n</div>\n<div class="subactions">\n<a class="subaction" href="{{url_for(\'backup\')}}">💾 Backup Data</a>\n<a class="subaction" href="{{url_for(\'share\')}}">♻️ Restore Data / Share</a>\n</div>\n</section>\n\n<div class="section-tabs">\n<div class="tab blue"><div class="title">🧾 Pencatatan Pengeluaran</div><div class="small">Budget, transaksi, grafik & rekening</div><span class="chev">⌃</span></div>\n<a class="tab pink" href="{{url_for(\'goals_page\')}}"><div class="title">🎯 Target Tabungan</div><div class="small">Pantau target tabungan pilihan</div><span class="chev">⌄</span></a>\n</div>\n\n<div class="cards" style="margin-bottom:18px">\n<div class="mini"><div class="label">Pemasukan bulan ini</div><div class="num">{{income|rupiah}}</div></div>\n<div class="mini"><div class="label">Pengeluaran bulan ini</div><div class="num">{{expense|rupiah}}</div></div>\n<div class="mini"><div class="label">Saldo bersih</div><div class="num">{{(income-expense)|rupiah}}</div></div>\n<div class="mini"><div class="label">Masuk sebagai</div><div class="num">{{session.member_name}}</div></div>\n</div>\n\n{% for b in budgets %}\n<section class="budget-card">\n<div class="budget-head"><div class="budget-name">💙 Budget {{b.account.name}}</div><div class="budget-total">{{b.total|rupiah}} / bulan</div></div>\n{% set p=(b.spent/b.total*100) if b.total else 0 %}\n<div class="progress"><span style="width:{{[p,100]|min}}%"></span></div>\n<div class="used">{{b.spent|rupiah}} terpakai dari {{b.total|rupiah}}</div>\n{% for x in b.categories %}\n{% if x.budget or x.spent %}\n{% set cp=(x.spent/x.budget*100) if x.budget else 0 %}\n<div class="cat"><div class="catrow"><div class="catname">{{x.icon}} {{x.name}}</div><div class="catamount">{{x.spent|rupiah}} / {{x.budget|rupiah}}</div></div><div class="catbar"><span style="width:{{[cp,100]|min}}%"></span></div></div>\n{% endif %}\n{% endfor %}\n</section>\n{% endfor %}\n\n{% if recent %}\n<section class="budget-card"><div class="budget-name" style="margin-bottom:14px">🧾 Transaksi Terakhir</div><div class="table-wrap"><table class="table"><tr><th>Tanggal</th><th>Catatan</th><th>Dicatat oleh</th><th>Rekening</th><th>Jumlah</th></tr>{% for t in recent %}<tr><td>{{t.date}}</td><td>{{t.note or \'-\'}}</td><td>{{t.member_name}}</td><td>{{t.account_name}}</td><td class="{{\'green\' if t.kind==\'income\' else \'red\'}}">{{\'+\' if t.kind==\'income\' else \'-\'}} {{t.amount|rupiah}}</td></tr>{% endfor %}</table></div></section>\n{% endif %}\n</main>{% endblock %}', 'goals.html': '{% extends "base.html" %}{% block content %}<div class="form-card"><h1>🎯 Target Tabungan</h1><p class="muted">Pantau target tabungan pilihan keluarga.</p>{% for g in goals %}{% set p=(g.saved/g.target*100) if g.target else 0 %}<div class="mini" style="margin-bottom:12px"><div class="num">{{g.name}}</div><div class="muted">{{g.saved|rupiah}} / {{g.target|rupiah}}</div><div class="progress"><span style="width:{{[p,100]|min}}%"></span></div></div>{% endfor %}<h2>Tambah Target</h2><form method="post" style="padding:0;border:0;box-shadow:none"><div class="field"><label>Nama target</label><input name="name" placeholder="Contoh: Tabungan Rumah" required></div><div class="field"><label>Target nominal</label><input type="number" name="target" min="1" required></div><button class="btn pink">Simpan Target</button></form></div>{% endblock %}', 'join.html': '{% extends "base.html" %}{% block content %}<div class="form-card"><div class="logo">BudgetKu 💰</div><h1>Gabung akun bersama</h1><p class="muted">Masukkan kode share yang diberikan pemilik akun. Kamu akan melihat data BudgetKu yang sama.</p><form method="post"><div class="field"><label>Kode Share</label><input name="share_code" placeholder="BK-XXXXXXXX" required></div><div class="field"><label>Nama kamu</label><input name="member_name" placeholder="Suami" required></div><button class="btn pink" style="width:100%">Gabung Akun</button></form></div>{% endblock %}', 'login.html': '{% extends "base.html" %}{% block content %}<div class="form-card"><div class="logo">BudgetKu 💰</div><p class="tagline">Keuangan keluarga, lebih rapi, terarah, dan terkontrol. 💙💗</p><h1>Masuk ke akun keluarga</h1><p class="muted">Gunakan akun yang sama di HP Putri dan HP Suami agar data keuangan selalu sama.</p><form method="post"><div class="field"><label>Email</label><input type="email" name="email" required></div><div class="field"><label>Password</label><input type="password" name="password" required></div><div class="field"><label>Masuk sebagai</label><select name="member_name"><option>Putri</option><option>Suami</option></select></div><button class="btn" style="width:100%">Masuk</button></form><p class="muted" style="margin-top:16px">Belum punya akun? <a href="{{url_for(\'register\')}}" style="color:#4f7c99;font-weight:800">Buat akun keluarga</a></p><p class="muted">Punya kode share? <a href="{{url_for(\'join\')}}" style="color:#4f7c99;font-weight:800">Gabung akun</a></p></div>{% endblock %}', 'register.html': '{% extends "base.html" %}{% block content %}<div class="form-card"><div class="logo">BudgetKu 💰</div><h1>Buat akun keluarga</h1><p class="muted">Satu akun dapat dipakai bersama dari beberapa HP.</p><form method="post"><div class="field"><label>Nama akun keluarga</label><input name="family_name" placeholder="Keuangan Putri & Suami" required></div><div class="field"><label>Email bersama</label><input type="email" name="email" required></div><div class="field"><label>Password</label><input type="password" name="password" minlength="6" required></div><button class="btn" style="width:100%">Buat Akun</button></form></div>{% endblock %}', 'share.html': '{% extends "base.html" %}{% block content %}<div class="form-card"><h1>👥 Akun Bersama</h1><p class="muted">Satu BudgetKu untuk Putri dan Suami. Data saldo, transaksi, budget, dan target tetap satu.</p><div class="share-card"><div class="muted">KODE SHARE</div><div class="share-code">{{family.share_code}}</div><div class="muted">Bagikan kode ini kepada orang yang ingin membuka BudgetKu keluarga dari HP lain.</div></div><h2>Anggota</h2>{% for m in members %}<div class="mini" style="margin-bottom:8px">👤 <b>{{m.name}}</b></div>{% endfor %}<p class="muted" style="margin-top:20px">Untuk perangkat lain: buka BudgetKu → Gabung Akun → masukkan kode share.</p></div>{% endblock %}', 'transaction.html': '{% extends "base.html" %}{% block content %}<div class="form-card"><h1>Catat Transaksi</h1><p class="muted">Transaksi tersimpan di akun keluarga dan akan terlihat di HP lain.</p><form method="post"><div class="field"><label>Jenis</label><select name="kind"><option value="expense" {% if request.args.get(\'kind\')==\'expense\' %}selected{% endif %}>Pengeluaran</option><option value="income" {% if request.args.get(\'kind\')==\'income\' %}selected{% endif %}>Pemasukan</option></select></div><div class="field"><label>Dicatat oleh</label><select name="member_id">{% for m in members %}<option value="{{m.id}}" {% if m.name==session.member_name %}selected{% endif %}>{{m.name}}</option>{% endfor %}</select></div><div class="field"><label>Rekening</label><select name="account_id">{% for a in accounts %}<option value="{{a.id}}">{{a.name}} — {{a.balance|rupiah}}</option>{% endfor %}</select></div><div class="field"><label>Kategori</label><select name="category_id"><option value="">Tanpa kategori</option>{% for x in categories %}<option value="{{x.id}}">{{x.icon}} {{x.name}}</option>{% endfor %}</select></div><div class="field"><label>Jumlah</label><input type="number" name="amount" min="1" step="1" required></div><div class="field"><label>Tanggal</label><input type="date" name="date" value="{{today}}" required></div><div class="field"><label>Catatan</label><input name="note" placeholder="Contoh: belanja mingguan"></div><button class="btn">Simpan Transaksi</button></form></div>{% endblock %}'}
STYLE_CSS = '\n:root{\n --blue:#bfe7f8;--blue2:#dff4fc;--pink:#f7c6dc;--pink2:#fde5ef;\n --ink:#385a76;--dark:#344054;--muted:#8393a5;--bg:#edf8ff;--white:#fff;\n --line:#e5edf3;--lav:#e9e1f7;--accent:#9f8acb;\n}\n*{box-sizing:border-box}\nbody{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;color:var(--dark);\nbackground:linear-gradient(180deg,#e6f6ff 0%,#f7f8ff 55%,#f8f2fb 100%);min-height:100vh}\na{text-decoration:none;color:inherit}\n.nav{position:sticky;top:0;z-index:10;background:rgba(255,255,255,.92);backdrop-filter:blur(10px);border-bottom:1px solid #e4edf3;\npadding:11px 16px;display:flex;justify-content:space-between;align-items:center}\n.brand{font-size:23px;font-weight:900;color:#3b6687}.navlinks{display:flex;gap:9px;align-items:center;font-size:12px;color:#5d7082}\n.container{max-width:900px;margin:0 auto;padding:22px 18px 50px}\n.hero-card{background:#fff;border:1px solid #edf0f3;border-radius:28px;padding:28px 32px;box-shadow:0 14px 40px #52758a14}\n.logo{font-size:42px;font-weight:900;color:#376689;letter-spacing:-2px}.logo span{font-size:36px}\n.tagline{font-size:17px;color:#8393a5;line-height:1.45;margin:8px 0 24px}\n.statsline{font-size:16px;color:#8b9bad;margin-bottom:8px}.bigmoney{font-size:48px;font-weight:900;color:#365f7e;letter-spacing:-2px;margin-bottom:25px}\n.actions{display:grid;grid-template-columns:1fr 1fr;gap:18px}.action{border:0;border-radius:20px;padding:17px;font-size:18px;font-weight:800;cursor:pointer}\n.action.blue{background:#bce4f7;color:#285978}.action.pink{background:#f5c4da;color:#70405b}\n.action.light{background:#edf6fb;color:#496a80}.wide{grid-column:1/-1}\n.subactions{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:14px}.subaction{border:0;border-radius:20px;padding:15px;background:#edf6fb;color:#4a6a80;font-weight:800;font-size:16px;cursor:pointer}\n.section-tabs{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:34px 0 18px}.tab{border-radius:28px;padding:18px 22px;font-weight:800;position:relative}.tab.blue{background:#c8ebfb}.tab.pink{background:#f9cce0}.tab .title{font-size:18px;color:#415873}.tab .small{font-size:12px;color:#6f8092;margin-top:4px}.chev{position:absolute;right:18px;bottom:17px}\n.budget-card{background:#fff;border-radius:28px;border:1px solid #edf0f3;padding:26px 34px;box-shadow:0 12px 34px #52758a10;margin-bottom:20px}\n.budget-head{display:flex;justify-content:space-between;align-items:flex-start;gap:15px}.budget-name{font-size:25px;font-weight:900;color:#344b60}.budget-total{font-size:20px;font-weight:900;color:#3e4c5d}\n.progress{height:12px;background:#eaf2f7;border-radius:99px;overflow:hidden;margin:22px 0 18px}.progress span{display:block;height:100%;background:linear-gradient(90deg,#9edcf3,#efb6d3);border-radius:99px}\n.used{color:#8999aa;font-size:15px;margin-bottom:12px}.cat{padding:17px 0;border-bottom:1px solid #edf1f4}.cat:last-child{border-bottom:0}.catrow{display:flex;justify-content:space-between;gap:12px;align-items:center}.catname{font-size:17px;color:#405164}.catamount{font-size:16px;color:#3d4a59;font-weight:700}.catbar{height:9px;background:#edf3f6;border-radius:99px;margin-top:12px;overflow:hidden}.catbar span{display:block;height:100%;background:linear-gradient(90deg,#9edcf3,#efb6d3);border-radius:99px}\n.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.mini{background:#fff;border:1px solid #e9eef3;border-radius:18px;padding:15px}.mini .label{font-size:11px;color:#8a99a8}.mini .num{font-size:18px;font-weight:900;margin-top:5px;color:#3e5c75}\n.form-card{max-width:560px;margin:40px auto;background:#fff;border-radius:26px;padding:28px;box-shadow:0 15px 40px #52758a12}.form-card h1{color:#3a6380;margin-top:0}.field{margin:0 0 15px}.field label{display:block;font-size:13px;font-weight:800;margin-bottom:6px;color:#526679}.field input,.field select{width:100%;padding:12px;border:1px solid #dbe6ed;border-radius:12px;font:inherit;background:#fff}.btn{display:inline-block;border:0;border-radius:12px;padding:12px 16px;background:#77bfe0;color:#fff;font-weight:800;cursor:pointer}.btn.pink{background:#e7a6c3}.muted{color:#8797a7;font-size:13px}.flash{padding:12px 14px;border-radius:12px;background:#fff0f3;color:#b04d67;margin-bottom:12px}\n.share-card{background:linear-gradient(135deg,#e6f7ff,#fff0f7);border:1px solid #e5edf3;border-radius:24px;padding:24px;text-align:center}.share-code{font-size:36px;font-weight:950;letter-spacing:4px;color:#466c88;margin:12px 0}\n.table-wrap{overflow:auto;background:#fff;border-radius:20px;border:1px solid #e8eef2}.table{width:100%;border-collapse:collapse;min-width:650px}.table th,.table td{padding:13px;border-bottom:1px solid #edf1f4;text-align:left;font-size:13px}.table th{color:#8292a2}\n@media(max-width:650px){\n .container{padding:14px 12px 40px}.hero-card{padding:23px 20px;border-radius:24px}.logo{font-size:34px}.tagline{font-size:15px}.bigmoney{font-size:36px}\n .actions{gap:10px}.action{font-size:15px;padding:14px}.subactions{gap:9px}.subaction{font-size:13px;padding:13px}\n .section-tabs{gap:10px;margin-top:20px}.tab{padding:15px;border-radius:21px}.tab .title{font-size:15px}.tab .small{font-size:10px}\n .budget-card{padding:21px 17px;border-radius:23px}.budget-name{font-size:21px}.budget-total{font-size:16px}.catname{font-size:15px}.catamount{font-size:14px}\n .cards{grid-template-columns:1fr 1fr}.navlinks{gap:6px;font-size:10px}.brand{font-size:19px}\n}\n'
app.jinja_loader = DictLoader(TEMPLATES)

@app.route("/static/<path:filename>")
def static_file(filename):
    if filename == "style.css":
        return Response(STYLE_CSS, mimetype="text/css")
    return ("Not found", 404)

DEFAULT_ACCOUNTS = [
    ("BRI Simpedes", "Bank"),
    ("BRI Junio", "Bank"),
    ("Jenius Kontrakan", "Bank"),
    ("Jenius Dana Darurat", "Bank"),
    ("Mandiri", "Bank"),
]
DEFAULT_CATEGORIES = [
    ("Listrik & Air", "⚡"),
    ("Belanja Mingguan", "🛒"),
    ("Kebutuhan Rumah", "🏠"),
    ("Personal Care", "💄"),
    ("Transportasi", "🚗"),
    ("Main & Hiburan", "🎡"),
    ("Sedekah", "🤲"),
    ("Tabungan Tetap Simpedes", "💰"),
    ("Dana Darurat Bulanan", "🛟"),
]


def using_postgres():
    return bool(DATABASE_URL)


def normalized_database_url():
    url = DATABASE_URL
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


def db():
    """Return a DB-API connection for either local SQLite or production PostgreSQL."""
    if using_postgres():
        if psycopg is None:
            raise RuntimeError("DATABASE_URL is set, but psycopg is not installed.")
        return psycopg.connect(normalized_database_url(), row_factory=dict_row)
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    c = db()
    if using_postgres():
        statements = [
            """CREATE TABLE IF NOT EXISTS families (
                id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                share_code TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS members (
                id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                family_id INTEGER NOT NULL REFERENCES families(id),
                name TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                family_id INTEGER NOT NULL REFERENCES families(id),
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                balance DOUBLE PRECISION NOT NULL DEFAULT 0
            )""",
            """CREATE TABLE IF NOT EXISTS categories (
                id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                family_id INTEGER NOT NULL REFERENCES families(id),
                name TEXT NOT NULL,
                icon TEXT NOT NULL DEFAULT '•'
            )""",
            """CREATE TABLE IF NOT EXISTS budgets (
                id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                family_id INTEGER NOT NULL REFERENCES families(id),
                account_id INTEGER NOT NULL REFERENCES accounts(id),
                category_id INTEGER NOT NULL REFERENCES categories(id),
                month TEXT NOT NULL,
                amount DOUBLE PRECISION NOT NULL DEFAULT 0,
                UNIQUE(family_id, account_id, category_id, month)
            )""",
            """CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                family_id INTEGER NOT NULL REFERENCES families(id),
                member_id INTEGER NOT NULL REFERENCES members(id),
                account_id INTEGER NOT NULL REFERENCES accounts(id),
                category_id INTEGER REFERENCES categories(id),
                kind TEXT NOT NULL,
                amount DOUBLE PRECISION NOT NULL,
                note TEXT,
                date TEXT NOT NULL,
                created_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS goals (
                id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                family_id INTEGER NOT NULL REFERENCES families(id),
                name TEXT NOT NULL,
                target DOUBLE PRECISION NOT NULL,
                saved DOUBLE PRECISION NOT NULL DEFAULT 0
            )""",
            "CREATE INDEX IF NOT EXISTS idx_members_family ON members(family_id)",
            "CREATE INDEX IF NOT EXISTS idx_accounts_family ON accounts(family_id)",
            "CREATE INDEX IF NOT EXISTS idx_categories_family ON categories(family_id)",
            "CREATE INDEX IF NOT EXISTS idx_transactions_family_date ON transactions(family_id, date)",
        ]
        for statement in statements:
            c.execute(statement)
    else:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS families (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            share_code TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            family_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            FOREIGN KEY(family_id) REFERENCES families(id)
        );
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            family_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            balance REAL NOT NULL DEFAULT 0,
            FOREIGN KEY(family_id) REFERENCES families(id)
        );
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            family_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            icon TEXT NOT NULL DEFAULT '•',
            FOREIGN KEY(family_id) REFERENCES families(id)
        );
        CREATE TABLE IF NOT EXISTS budgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            family_id INTEGER NOT NULL,
            account_id INTEGER NOT NULL,
            category_id INTEGER NOT NULL,
            month TEXT NOT NULL,
            amount REAL NOT NULL DEFAULT 0,
            UNIQUE(family_id, account_id, category_id, month)
        );
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            family_id INTEGER NOT NULL,
            member_id INTEGER NOT NULL,
            account_id INTEGER NOT NULL,
            category_id INTEGER,
            kind TEXT NOT NULL,
            amount REAL NOT NULL,
            note TEXT,
            date TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            family_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            target REAL NOT NULL,
            saved REAL NOT NULL DEFAULT 0,
            FOREIGN KEY(family_id) REFERENCES families(id)
        );
        """)
    c.commit()
    c.close()


def seed_family(fid):
    c = db()
    for name in ["Putri", "Suami"]:
        c.execute("INSERT INTO members(family_id,name) VALUES(?,?)", (fid, name))
    for name, typ in DEFAULT_ACCOUNTS:
        c.execute("INSERT INTO accounts(family_id,name,type) VALUES(?,?,?)", (fid, name, typ))
    for name, icon in DEFAULT_CATEGORIES:
        c.execute("INSERT INTO categories(family_id,name,icon) VALUES(?,?,?)", (fid, name, icon))
    c.commit()
    c.close()


def current_family():
    return session.get("family_id")


def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not current_family():
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapped


def make_code():
    return "BK-" + secrets.token_hex(4).upper()


def money(n):
    return "Rp{:,.0f}".format(n).replace(",", ".")


@app.template_filter("rupiah")
def rupiah(n):
    return money(n or 0)


@app.route("/")
def index():
    return redirect(url_for("dashboard") if current_family() else url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        family_name = request.form["family_name"].strip()
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        if not family_name or not email or len(password) < 6:
            flash("Lengkapi data dan gunakan password minimal 6 karakter.", "error")
            return render_template("register.html")
        c = db()
        try:
            if using_postgres():
                cur = c.execute(
                    """INSERT INTO families(name,email,password_hash,share_code,created_at)
                       VALUES(?,?,?,?,?) RETURNING id""",
                    (family_name, email, generate_password_hash(password), make_code(), datetime.now().isoformat())
                )
                fid = cur.fetchone()["id"]
            else:
                cur = c.execute(
                    "INSERT INTO families(name,email,password_hash,share_code,created_at) VALUES(?,?,?,?,?)",
                    (family_name, email, generate_password_hash(password), make_code(), datetime.now().isoformat())
                )
                fid = cur.lastrowid
            c.commit()
        except Exception as e:
            c.rollback()
            c.close()
            # Both SQLite and PostgreSQL raise an integrity error for duplicate email.
            if "unique" in str(e).lower() or "duplicate" in str(e).lower():
                flash("Email sudah terdaftar.", "error")
            else:
                flash("Pendaftaran gagal. Coba lagi.", "error")
            return render_template("register.html")
        c.close()
        seed_family(fid)
        session.update(family_id=fid, family_name=family_name, member_name="Putri")
        return redirect(url_for("dashboard"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        c = db()
        f = c.execute("SELECT * FROM families WHERE email=?", (email,)).fetchone()
        c.close()
        if f and check_password_hash(f["password_hash"], password):
            session.update(family_id=f["id"], family_name=f["name"],
                           member_name=request.form.get("member_name") or "Putri")
            return redirect(url_for("dashboard"))
        flash("Email atau password salah.", "error")
    return render_template("login.html")


@app.route("/join", methods=["GET", "POST"])
def join():
    if request.method == "POST":
        code = request.form["share_code"].strip().upper()
        member = request.form["member_name"].strip() or "Anggota"
        c = db()
        f = c.execute("SELECT * FROM families WHERE share_code=?", (code,)).fetchone()
        if not f:
            c.close()
            flash("Kode share tidak ditemukan.", "error")
            return render_template("join.html")
        session.update(family_id=f["id"], family_name=f["name"], member_name=member)
        exists = c.execute("SELECT id FROM members WHERE family_id=? AND name=?", (f["id"], member)).fetchone()
        if not exists:
            c.execute("INSERT INTO members(family_id,name) VALUES(?,?)", (f["id"], member))
            c.commit()
        c.close()
        return redirect(url_for("dashboard"))
    return render_template("join.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    fid = current_family()
    month = datetime.now().strftime("%Y-%m")
    c = db()
    accounts = c.execute("SELECT * FROM accounts WHERE family_id=? ORDER BY id", (fid,)).fetchall()
    total = sum(a["balance"] for a in accounts)
    income = c.execute("SELECT COALESCE(SUM(amount),0) n FROM transactions WHERE family_id=? AND kind='income' AND substr(date,1,7)=?", (fid, month)).fetchone()["n"]
    expense = c.execute("SELECT COALESCE(SUM(amount),0) n FROM transactions WHERE family_id=? AND kind='expense' AND substr(date,1,7)=?", (fid, month)).fetchone()["n"]
    tx_count = c.execute("SELECT COUNT(*) n FROM transactions WHERE family_id=?", (fid,)).fetchone()["n"]
    recent = c.execute("""
        SELECT t.*, m.name member_name, a.name account_name, cat.name category_name, cat.icon
        FROM transactions t
        JOIN members m ON m.id=t.member_id
        JOIN accounts a ON a.id=t.account_id
        LEFT JOIN categories cat ON cat.id=t.category_id
        WHERE t.family_id=? ORDER BY t.date DESC,t.id DESC LIMIT 10
    """, (fid,)).fetchall()
    budget_accounts = c.execute("SELECT * FROM accounts WHERE family_id=?", (fid,)).fetchall()
    budgets = []
    for a in budget_accounts:
        total_budget = c.execute("SELECT COALESCE(SUM(amount),0) n FROM budgets WHERE family_id=? AND account_id=? AND month=?", (fid, a["id"], month)).fetchone()["n"]
        spent = c.execute("""SELECT COALESCE(SUM(t.amount),0) n FROM transactions t
            WHERE t.family_id=? AND t.account_id=? AND t.kind='expense' AND substr(t.date,1,7)=?""",
            (fid, a["id"], month)).fetchone()["n"]
        cats = c.execute("""SELECT c.id,c.name,c.icon,COALESCE(b.amount,0) budget,
            COALESCE((SELECT SUM(t.amount) FROM transactions t WHERE t.family_id=? AND t.account_id=? AND t.category_id=c.id
            AND t.kind='expense' AND substr(t.date,1,7)=?),0) spent
            FROM categories c LEFT JOIN budgets b ON b.category_id=c.id AND b.account_id=? AND b.family_id=? AND b.month=?
            WHERE c.family_id=? ORDER BY c.id""",
            (fid, a["id"], month, a["id"], fid, month, fid)).fetchall()
        if total_budget > 0 or any(x["budget"] > 0 for x in cats):
            budgets.append({"account": a, "total": total_budget, "spent": spent, "categories": cats})
    goals = c.execute("SELECT * FROM goals WHERE family_id=? ORDER BY id", (fid,)).fetchall()
    c.close()
    return render_template("dashboard.html", accounts=accounts, total=total, income=income,
                           expense=expense, tx_count=tx_count, recent=recent,
                           budgets=budgets, goals=goals, month=month)


@app.route("/transaction", methods=["GET", "POST"])
@login_required
def transaction():
    fid = current_family()
    c = db()
    members = c.execute("SELECT * FROM members WHERE family_id=?", (fid,)).fetchall()
    accounts = c.execute("SELECT * FROM accounts WHERE family_id=?", (fid,)).fetchall()
    cats = c.execute("SELECT * FROM categories WHERE family_id=?", (fid,)).fetchall()
    if request.method == "POST":
        member_id = int(request.form["member_id"])
        account_id = int(request.form["account_id"])
        category_id = request.form.get("category_id") or None
        if category_id:
            category_id = int(category_id)
        kind = request.form["kind"]
        amount = float(request.form["amount"])
        date = request.form.get("date") or datetime.now().date().isoformat()
        note = request.form.get("note", "").strip()
        member_ok = c.execute("SELECT id FROM members WHERE id=? AND family_id=?", (member_id, fid)).fetchone()
        account = c.execute("SELECT * FROM accounts WHERE id=? AND family_id=?", (account_id, fid)).fetchone()
        category_ok = (category_id is None or c.execute("SELECT id FROM categories WHERE id=? AND family_id=?", (category_id, fid)).fetchone())
        if not member_ok or not account or not category_ok or kind not in ("income", "expense") or amount <= 0:
            flash("Data transaksi tidak valid.", "error")
        else:
            delta = amount if kind == "income" else -amount
            c.execute("UPDATE accounts SET balance=balance+? WHERE id=? AND family_id=?", (delta, account_id, fid))
            c.execute("""INSERT INTO transactions
                (family_id,member_id,account_id,category_id,kind,amount,note,date,created_at)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                (fid, member_id, account_id, category_id, kind, amount, note, date, datetime.now().isoformat()))
            c.commit()
            c.close()
            return redirect(url_for("dashboard"))
    c.close()
    return render_template("transaction.html", members=members, accounts=accounts,
                           categories=cats, today=datetime.now().date().isoformat())


@app.route("/accounts", methods=["GET", "POST"])
@login_required
def accounts_page():
    fid = current_family()
    c = db()
    if request.method == "POST":
        name = request.form["name"].strip()
        typ = request.form.get("type", "Bank")
        balance = float(request.form.get("balance") or 0)
        if name:
            c.execute("INSERT INTO accounts(family_id,name,type,balance) VALUES(?,?,?,?)", (fid, name, typ, balance))
            c.commit()
        c.close()
        return redirect(url_for("accounts_page"))
    accounts = c.execute("SELECT * FROM accounts WHERE family_id=? ORDER BY id", (fid,)).fetchall()
    c.close()
    return render_template("accounts.html", accounts=accounts)


@app.route("/budgets", methods=["GET", "POST"])
@login_required
def budgets_page():
    fid = current_family()
    month = request.values.get("month") or datetime.now().strftime("%Y-%m")
    c = db()
    accounts = c.execute("SELECT * FROM accounts WHERE family_id=?", (fid,)).fetchall()
    cats = c.execute("SELECT * FROM categories WHERE family_id=?", (fid,)).fetchall()
    if request.method == "POST":
        account_id = int(request.form["account_id"])
        category_id = int(request.form["category_id"])
        amount = float(request.form["amount"])
        valid = c.execute("SELECT id FROM accounts WHERE id=? AND family_id=?", (account_id, fid)).fetchone() and \
                c.execute("SELECT id FROM categories WHERE id=? AND family_id=?", (category_id, fid)).fetchone()
        if valid:
            c.execute("""INSERT INTO budgets(family_id,account_id,category_id,month,amount)
                         VALUES(?,?,?,?,?) ON CONFLICT(family_id,account_id,category_id,month)
                         DO UPDATE SET amount=excluded.amount""", (fid, account_id, category_id, month, amount))
            c.commit()
        else:
            flash("Rekening atau kategori tidak valid.", "error")
    c.close()
    return render_template("budgets.html", accounts=accounts, categories=cats, month=month)


@app.route("/goals", methods=["GET", "POST"])
@login_required
def goals_page():
    fid = current_family()
    c = db()
    if request.method == "POST":
        name = request.form["name"].strip()
        target = float(request.form["target"])
        if name and target > 0:
            c.execute("INSERT INTO goals(family_id,name,target,saved) VALUES(?,?,?,0)", (fid, name, target))
            c.commit()
    goals = c.execute("SELECT * FROM goals WHERE family_id=?", (fid,)).fetchall()
    c.close()
    return render_template("goals.html", goals=goals)


@app.route("/share")
@login_required
def share():
    c = db()
    f = c.execute("SELECT name,email,share_code FROM families WHERE id=?", (current_family(),)).fetchone()
    members = c.execute("SELECT * FROM members WHERE family_id=?", (current_family(),)).fetchall()
    c.close()
    return render_template("share.html", family=f, members=members)


@app.route("/backup")
@login_required
def backup():
    fid = current_family()
    c = db()
    data = {
        "version": "BudgetKu Final Shared v2 PostgreSQL-ready",
        "family": dict(c.execute("SELECT name,email,share_code FROM families WHERE id=?", (fid,)).fetchone()),
        "members": [dict(x) for x in c.execute("SELECT id,name FROM members WHERE family_id=?", (fid,)).fetchall()],
        "accounts": [dict(x) for x in c.execute("SELECT id,name,type,balance FROM accounts WHERE family_id=?", (fid,)).fetchall()],
        "categories": [dict(x) for x in c.execute("SELECT id,name,icon FROM categories WHERE family_id=?", (fid,)).fetchall()],
        "transactions": [dict(x) for x in c.execute("SELECT * FROM transactions WHERE family_id=?", (fid,)).fetchall()],
        "budgets": [dict(x) for x in c.execute("SELECT * FROM budgets WHERE family_id=?", (fid,)).fetchall()],
        "goals": [dict(x) for x in c.execute("SELECT * FROM goals WHERE family_id=?", (fid,)).fetchall()],
    }
    c.close()
    resp = jsonify(data)
    resp.headers["Content-Disposition"] = "attachment; filename=budgetku-backup.json"
    return resp


# Initialize the schema on startup. In production, DATABASE_URL points to Render Postgres;
# locally, the app keeps using budgetku.db so the project remains easy to test.
init_db()

if __name__ == "__main__":
    app.run(debug=True)
