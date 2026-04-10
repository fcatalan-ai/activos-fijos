bash

cat /home/claude/activos_app/app.py
Salida

from flask import Flask, render_template, request, jsonify, redirect, url_for, session, send_file
import sqlite3, os, io, base64, struct, zlib
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'activos-colegio-2025-secret')
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'activos.db')

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS activos (
        id TEXT PRIMARY KEY,
        tipo TEXT, subtipo TEXT, marca TEXT, modelo TEXT, serie TEXT,
        estado TEXT, edificio TEXT, sala TEXT, responsable TEXT,
        fecha_compra TEXT, precio REAL, documento TEXT, vida_util INTEGER,
        observaciones TEXT, foto TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS movimientos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        activo_id TEXT, tipo TEXT, descripcion TEXT,
        usuario TEXT, fecha TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT, email TEXT UNIQUE, password TEXT, rol TEXT DEFAULT 'consulta'
    )''')
    c.execute("INSERT OR IGNORE INTO usuarios (nombre,email,password,rol) VALUES (?,?,?,?)",
              ('Administrador',
               os.environ.get('ADMIN_EMAIL','admin@colegio.cl'),
               os.environ.get('ADMIN_PASS','admin123'),
               'admin'))
    conn.commit()
    conn.close()

# Llamar init_db al cargar el módulo
with app.app_context():
    init_db()

def next_id():
    year = datetime.now().year % 100
    conn = get_db()
    rows = conn.execute("SELECT id FROM activos WHERE id LIKE 'AF-%'").fetchall()
    conn.close()
    nums = []
    for r in rows:
        parts = r['id'].split('-')
        if len(parts) == 3:
            try: nums.append(int(parts[2]))
            except: pass
    nxt = max(nums) + 1 if nums else 1000
    return f"AF-{year:02d}-{nxt}"

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user' not in session:
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user' not in session:
            return redirect('/login')
        if session.get('rol') != 'admin':
            return jsonify({'error': 'Sin permisos'}), 403
        return f(*args, **kwargs)
    return decorated

@app.route('/login', methods=['GET','POST'])
def login():
    error = ''
    if request.method == 'POST':
        email = request.form.get('email','').strip()
        password = request.form.get('password','')
        conn = get_db()
        u = conn.execute("SELECT * FROM usuarios WHERE email=? AND password=?", (email, password)).fetchone()
        conn.close()
        if u:
            session['user'] = u['nombre']
            session['rol'] = u['rol']
            session['email'] = u['email']
            return redirect('/')
        error = 'Email o contraseña incorrectos'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

@app.route('/')
@login_required
def index():
    return render_template('index.html', user=session['user'], rol=session['rol'])

@app.route('/api/activos', methods=['GET'])
@login_required
def get_activos():
    conn = get_db()
    q = request.args.get('q','')
    tipo = request.args.get('tipo','')
    estado = request.args.get('estado','')
    edificio = request.args.get('edificio','')
    sql = "SELECT * FROM activos WHERE 1=1"
    params = []
    if q:
        sql += " AND (id LIKE ? OR marca LIKE ? OR modelo LIKE ? OR serie LIKE ? OR responsable LIKE ?)"
        p = f'%{q}%'
        params += [p,p,p,p,p]
    if tipo: sql += " AND tipo=?"; params.append(tipo)
    if estado: sql += " AND estado=?"; params.append(estado)
    if edificio: sql += " AND edificio=?"; params.append(edificio)
    sql += " ORDER BY id DESC"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/activos/<id>', methods=['GET'])
@login_required
def get_activo(id):
    conn = get_db()
    a = conn.execute("SELECT * FROM activos WHERE id=?", (id,)).fetchone()
    movs = conn.execute("SELECT * FROM movimientos WHERE activo_id=? ORDER BY fecha DESC", (id,)).fetchall()
    conn.close()
    if not a: return jsonify({'error':'No encontrado'}), 404
    return jsonify({'activo': dict(a), 'movimientos': [dict(m) for m in movs]})

@app.route('/api/activos', methods=['POST'])
@admin_required
def crear_activo():
    data = request.json
    aid = next_id()
    conn = get_db()
    conn.execute('''INSERT INTO activos
        (id,tipo,subtipo,marca,modelo,serie,estado,edificio,sala,responsable,
         fecha_compra,precio,documento,vida_util,observaciones)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (aid, data.get('tipo'), data.get('subtipo'), data.get('marca'),
         data.get('modelo'), data.get('serie'), data.get('estado','Bueno'),
         data.get('edificio'), data.get('sala'), data.get('responsable'),
         data.get('fecha_compra'), data.get('precio',0), data.get('documento'),
         data.get('vida_util',4), data.get('observaciones','')))
    conn.execute("INSERT INTO movimientos (activo_id,tipo,descripcion,usuario) VALUES (?,?,?,?)",
                 (aid, 'Alta', 'Activo registrado en el sistema', session['user']))
    conn.commit()
    conn.close()
    return jsonify({'id': aid, 'ok': True})

@app.route('/api/activos/<id>', methods=['PUT'])
@admin_required
def editar_activo(id):
    data = request.json
    conn = get_db()
    old = conn.execute("SELECT * FROM activos WHERE id=?", (id,)).fetchone()
    if not old: return jsonify({'error':'No encontrado'}), 404
    campos = ['tipo','subtipo','marca','modelo','serie','estado','edificio','sala',
              'responsable','fecha_compra','precio','documento','vida_util','observaciones']
    sets = ', '.join(f"{c}=?" for c in campos if c in data)
    vals = [data[c] for c in campos if c in data]
    if sets:
        conn.execute(f"UPDATE activos SET {sets} WHERE id=?", vals + [id])
    cambios = []
    for c in ['estado','edificio','sala','responsable']:
        if c in data and str(old[c]) != str(data[c]):
            cambios.append(f"{c}: '{old[c]}' → '{data[c]}'")
    if cambios:
        conn.execute("INSERT INTO movimientos (activo_id,tipo,descripcion,usuario) VALUES (?,?,?,?)",
                     (id, 'Edición', ' | '.join(cambios), session['user']))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/activos/<id>/traslado', methods=['POST'])
@admin_required
def traslado(id):
    data = request.json
    conn = get_db()
    old = conn.execute("SELECT edificio,sala,responsable FROM activos WHERE id=?", (id,)).fetchone()
    conn.execute("UPDATE activos SET edificio=?,sala=?,responsable=? WHERE id=?",
                 (data['edificio'], data['sala'], data.get('responsable',''), id))
    desc = f"Traslado: {old['sala']} → {data['sala']} | Responsable: {data.get('responsable','—')}"
    conn.execute("INSERT INTO movimientos (activo_id,tipo,descripcion,usuario) VALUES (?,?,?,?)",
                 (id, 'Traslado', desc, session['user']))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

def make_simple_qr_png(text):
    """Genera un PNG minimalista con patrón basado en el texto (sin librería externa)."""
    size = 21
    cell = 10
    img_size = size * cell + 20
    # Patrón determinista basado en el texto
    seed = sum(ord(c) * (i+1) for i, c in enumerate(text))
    def is_dark(r, c):
        # Finder patterns
        if (r < 7 and c < 7) or (r < 7 and c >= size-7) or (r >= size-7 and c < 7):
            if r == 0 or r == 6 or c == 0 or c == 6: return True
            if 2 <= r <= 4 and 2 <= c <= 4: return True
            return False
        return (seed * (r+1) * (c+1) + r * 3 + c * 7) % 4 != 0

    # Crear imagen PNG raw
    pixels = []
    pad = 10
    w = img_size
    h = img_size
    rgba = []
    for y in range(h):
        for x in range(w):
            rx = x - pad
            ry = y - pad
            r_cell = ry // cell
            c_cell = rx // cell
            if 0 <= r_cell < size and 0 <= c_cell < size and is_dark(r_cell, c_cell):
                rgba += [0, 0, 0, 255]
            else:
                rgba += [255, 255, 255, 255]

    def png_chunk(name, data):
        c = zlib.crc32(name + data) & 0xffffffff
        return struct.pack('>I', len(data)) + name + data + struct.pack('>I', c)

    raw_rows = b''
    for y in range(h):
        row = bytes([0])  # filter type
        for x in range(w):
            idx = (y * w + x) * 4
            row += bytes(rgba[idx:idx+4])
        raw_rows += row

    compressed = zlib.compress(raw_rows, 9)
    png = (b'\x89PNG\r\n\x1a\n' +
           png_chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)[:13]) +
           png_chunk(b'IDAT', compressed) +
           png_chunk(b'IEND', b''))
    # Fix IHDR
    ihdr_data = struct.pack('>II', w, h) + bytes([8, 2, 0, 0, 0])
    png = (b'\x89PNG\r\n\x1a\n' +
           png_chunk(b'IHDR', ihdr_data) +
           png_chunk(b'IDAT', compressed) +
           png_chunk(b'IEND', b''))
    return png

@app.route('/api/activos/<id>/qr')
@login_required
def get_qr(id):
    url = request.host_url + f'ficha/{id}'
    try:
        import qrcode
        img = qrcode.make(url)
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        b64 = base64.b64encode(buf.getvalue()).decode()
    except Exception:
        png = make_simple_qr_png(id)
        b64 = base64.b64encode(png).decode()
    return jsonify({'qr': b64, 'url': url})

@app.route('/ficha/<id>')
def ficha_publica(id):
    conn = get_db()
    a = conn.execute("SELECT * FROM activos WHERE id=?", (id,)).fetchone()
    conn.close()
    if not a: return "Activo no encontrado", 404
    return render_template('ficha_publica.html', a=dict(a))

@app.route('/api/stats')
@login_required
def stats():
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) as n FROM activos").fetchone()['n']
    buenos = conn.execute("SELECT COUNT(*) as n FROM activos WHERE estado='Bueno'").fetchone()['n']
    malos = conn.execute("SELECT COUNT(*) as n FROM activos WHERE estado='Malo'").fetchone()['n']
    valor = conn.execute("SELECT COALESCE(SUM(precio),0) as s FROM activos").fetchone()['s']
    por_edificio = conn.execute("SELECT edificio, COUNT(*) as n FROM activos GROUP BY edificio").fetchall()
    conn.close()
    return jsonify({'total': total, 'buenos': buenos, 'malos': malos,
                    'valor': valor, 'por_edificio': [dict(r) for r in por_edificio]})

@app.route('/api/export/excel')
@login_required
def export_excel():
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    conn = get_db()
    rows = conn.execute("SELECT * FROM activos ORDER BY id").fetchall()
    conn.close()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Activos Fijos"
    headers = ['ID Activo','Tipo','Subtipo','Marca','Modelo','N° Serie','Estado',
               'Edificio','Sala','Responsable','Fecha Compra','Precio','Documento',
               'Vida Útil','Observaciones']
    keys = ['id','tipo','subtipo','marca','modelo','serie','estado','edificio','sala',
            'responsable','fecha_compra','precio','documento','vida_util','observaciones']
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = PatternFill('solid', start_color='1F3864', fgColor='1F3864')
        cell.alignment = Alignment(horizontal='center')
        ws.column_dimensions[ws.cell(row=1,column=col).column_letter].width = 18
    for row_idx, row in enumerate(rows, 2):
        for col, key in enumerate(keys, 1):
            ws.cell(row=row_idx, column=col, value=row[key])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, download_name='activos_fijos.xlsx',
                     as_attachment=True,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

if __name__ == '__main__':
    init_db()
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
