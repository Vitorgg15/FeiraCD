from __future__ import annotations
import csv
import io
import os
import secrets
import shutil
import sqlite3
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from flask import Flask, jsonify, render_template, request, session, redirect, make_response
from werkzeug.security import check_password_hash, generate_password_hash

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "empresario.sqlite3"
DB_PATH.parent.mkdir(exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET") or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Strict",
    SESSION_COOKIE_SECURE=False,  # HTTP restrito à rede local do evento
    MAX_CONTENT_LENGTH=32 * 1024,
)

def admin_password_hash():
    configured = os.environ.get("ADMIN_PASSWORD", "")
    if len(configured) < 8:
        return None
    # Hash calculado em memória; a senha não é enviada ao navegador público.
    return generate_password_hash(configured)

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS participants(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL COLLATE NOCASE UNIQUE,
            phone TEXT NOT NULL,
            consent INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            best_revenue REAL NOT NULL DEFAULT 0,
            best_title TEXT NOT NULL DEFAULT 'Participante',
            games_played INTEGER NOT NULL DEFAULT 0
        )""")
        con.execute("""
        CREATE TABLE IF NOT EXISTS games(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            participant_id INTEGER NOT NULL REFERENCES participants(id),
            revenue REAL NOT NULL,
            cash REAL NOT NULL,
            title TEXT NOT NULL,
            played_at TEXT NOT NULL
        )""")

init_db()

def create_backup():
    """Cria uma cópia consistente do SQLite antes de qualquer reset."""
    backup_dir = ROOT / "backups"
    backup_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = backup_dir / f"empresario_{stamp}.sqlite3"
    source = sqlite3.connect(DB_PATH)
    destination = sqlite3.connect(target)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    return target.name

def validate_csrf():
    token = request.headers.get("X-CSRF-Token", "")
    expected = session.get("csrf", "")
    return bool(expected) and secrets.compare_digest(token, expected)

def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("admin"):
            return jsonify({"error": "Acesso administrativo necessário."}), 401
        return fn(*args, **kwargs)
    return wrapped

@app.after_request
def no_cache(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response

@app.get("/")
def game():
    return render_template("game.html")

@app.get("/ranking")
def ranking_page():
    return render_template("ranking.html")

@app.get("/admin")
def admin_page():
    return render_template("admin.html")

@app.post("/api/register")
def register():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    phone = str(data.get("phone", "")).strip()
    consent = bool(data.get("consent"))
    if not (2 <= len(username) <= 30):
        return jsonify({"error": "O nome de usuário deve ter entre 2 e 30 caracteres."}), 400
    digits = "".join(ch for ch in phone if ch.isdigit())
    if not (10 <= len(digits) <= 13):
        return jsonify({"error": "Informe um telefone válido com DDD."}), 400
    if not consent:
        return jsonify({"error": "É necessário autorizar o contato da organização sobre a atividade."}), 400
    now = datetime.now(timezone.utc).isoformat()
    with db() as con:
        existing = con.execute("SELECT id, phone FROM participants WHERE username=?", (username,)).fetchone()
        if existing:
            # Reutilização do cadastro exige que o telefone informado corresponda ao já cadastrado.
            if "".join(ch for ch in existing["phone"] if ch.isdigit()) != digits:
                return jsonify({"error": "Esse nome já está cadastrado. Procure a organização para recuperar seu acesso."}), 409
            pid = existing["id"]
            con.execute("UPDATE participants SET consent=1 WHERE id=?", (pid,))
        else:
            cur = con.execute(
                "INSERT INTO participants(username,phone,consent,created_at) VALUES(?,?,1,?)",
                (username, phone, now)
            )
            pid = cur.lastrowid
    session["participant_id"] = pid
    session["participant_name"] = username
    return jsonify({"ok": True, "username": username})

@app.post("/api/finish")
def finish_game():
    if not session.get("participant_id"):
        return jsonify({"error": "Faça o cadastro antes de enviar o resultado."}), 401
    data = request.get_json(silent=True) or {}
    try:
        revenue = float(data.get("revenue"))
        cash = float(data.get("cash"))
        title = str(data.get("title", "Participante"))[:100]
        if not (0 <= revenue <= 1_000_000_000 and -1_000_000_000 <= cash <= 1_000_000_000):
            raise ValueError()
    except (TypeError, ValueError):
        return jsonify({"error": "Resultado inválido."}), 400
    pid = session["participant_id"]
    now = datetime.now(timezone.utc).isoformat()
    with db() as con:
        con.execute(
            "INSERT INTO games(participant_id,revenue,cash,title,played_at) VALUES(?,?,?,?,?)",
            (pid, revenue, cash, title, now)
        )
        con.execute("""
            UPDATE participants
            SET games_played=games_played+1,
                best_revenue=MAX(best_revenue, ?),
                best_title=CASE WHEN ?>=best_revenue THEN ? ELSE best_title END
            WHERE id=?
        """, (revenue, revenue, title, pid))
    return jsonify({"ok": True})

@app.get("/api/ranking")
def public_ranking():
    with db() as con:
        rows = con.execute("""
            SELECT username, best_title AS title, best_revenue AS revenue
            FROM participants
            WHERE games_played > 0
            ORDER BY best_revenue DESC, username COLLATE NOCASE ASC
            LIMIT 100
        """).fetchall()
    return jsonify({"ranking": [dict(r) for r in rows], "updated_at": datetime.now(timezone.utc).isoformat()})

@app.post("/api/admin/login")
def admin_login():
    data = request.get_json(silent=True) or {}
    configured = os.environ.get("ADMIN_PASSWORD", "")
    if len(configured) < 8:
        return jsonify({"error": "Senha administrativa não configurada. Reinicie pelo arquivo iniciar_servidor.bat."}), 503
    supplied = str(data.get("password", ""))
    # Comparação segura contra a senha configurada no ambiente do servidor.
    if secrets.compare_digest(supplied, configured):
        session.clear()
        session["admin"] = True
        session["csrf"] = secrets.token_urlsafe(24)
        return jsonify({"ok": True, "csrf": session["csrf"]})
    return jsonify({"error": "Senha incorreta."}), 401

@app.post("/api/admin/logout")
@admin_required
def admin_logout():
    if not validate_csrf():
        return jsonify({"error": "Sessão inválida. Atualize o painel e tente novamente."}), 403
    session.clear()
    return jsonify({"ok": True})

@app.get("/api/admin/participants")
@admin_required
def admin_participants():
    with db() as con:
        rows = con.execute("""
            SELECT p.id,p.username,p.phone,p.best_title,p.best_revenue,p.games_played,p.created_at
            FROM participants p
            ORDER BY p.best_revenue DESC, p.username COLLATE NOCASE ASC
        """).fetchall()
    return jsonify({"participants": [dict(r) for r in rows]})

@app.get("/api/admin/export.csv")
@admin_required
def admin_export():
    with db() as con:
        rows = con.execute("""
            SELECT username,phone,best_title,best_revenue,games_played,created_at
            FROM participants
            ORDER BY best_revenue DESC, username COLLATE NOCASE ASC
        """).fetchall()
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["Nome de usuário","Telefone","Título","Faturamento (R$)","Partidas","Cadastro"])
    for r in rows:
        writer.writerow([r["username"],r["phone"],r["best_title"],f'{r["best_revenue"]:.2f}',r["games_played"],r["created_at"]])
    response = make_response("\ufeff" + output.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = 'attachment; filename="participantes_empresario.csv"'
    return response

@app.post("/api/admin/reset-ranking")
@admin_required
def reset_ranking():
    if not validate_csrf():
        return jsonify({"error": "Sessão inválida. Atualize o painel e tente novamente."}), 403
    backup_name = create_backup()
    with db() as con:
        con.execute("DELETE FROM games")
        con.execute("""
            UPDATE participants
            SET best_revenue=0, best_title='Participante', games_played=0
        """)
    return jsonify({"ok": True, "backup": backup_name,
                    "message": "Classificação zerada. Os cadastros foram mantidos."})

@app.post("/api/admin/new-edition")
@admin_required
def new_edition():
    if not validate_csrf():
        return jsonify({"error": "Sessão inválida. Atualize o painel e tente novamente."}), 403
    backup_name = create_backup()
    with db() as con:
        con.execute("DELETE FROM games")
        con.execute("DELETE FROM participants")
        # Reinicia os contadores para a nova edição.
        con.execute("DELETE FROM sqlite_sequence WHERE name IN ('games','participants')")
    session.pop("participant_id", None)
    session.pop("participant_name", None)
    return jsonify({"ok": True, "backup": backup_name,
                    "message": "Nova edição criada. Cadastros e resultados anteriores foram removidos da base ativa."})

@app.get("/api/health")
def health():
    return jsonify({"ok": True, "service": "Empresário por 5 Minutos - rede local"})

if __name__ == "__main__":
    if len(os.environ.get("ADMIN_PASSWORD", "")) < 8:
        print("ERRO: defina uma senha administrativa com pelo menos 8 caracteres no iniciar_servidor.bat.")
        raise SystemExit(1)
    print("\\nEmpresário por 5 Minutos - servidor local")
    print("No notebook público: http://127.0.0.1:5000")
    print("Nos outros notebooks: use o endereço IPv4 deste computador, por exemplo http://192.168.1.100:5000")
    print("Administração: /admin | Ranking para TV: /ranking")
    app.run(host="0.0.0.0", port=5000, threaded=True, debug=False)
