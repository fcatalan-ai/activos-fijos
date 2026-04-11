from flask import Flask, render_template, request, jsonify, redirect, url_for, session, send_file
import os, io, base64, struct, zlib
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'activos-colegio-2025-secret')

DATABASE_URL = os.environ.get('DATABASE_URL', '')

TIPOS = [
    'Equipamiento Tecnológico',
    'Equipamiento Audiovisual',
    'Equipamiento Deportivo',
    'Mobiliario',
    'Muebles y Útiles',
    'Otro',
]

def get_db():
    if DATABASE_URL:
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(DATABASE_URL)
        return conn, 'pg'
    else:
        import sqlite3
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'activos.db')
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn, 'sqlite'

def query(sql, params=(), fetchone=False, fetchall=False, commit=False):
    conn, mode = get_db()
    if mode == 'pg':
        import psycopg2.extras
        sql_pg = sql.replace('?', '%s').replace('INTEGER PRIMARY KEY AUTOINCREMENT', 'SERIAL PRIMARY KEY')
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    else:
        cur = conn.cursor()
    cur.execute(sql_pg if mode == 'pg' else sql, params)
    result = None
    if fetchone:
        row = cur.fetchone()
        result = dict(row) if row else None
    elif fetchall:
        rows = cur.fetchall()
        result = [dict(r) for r in rows]
    if commit:
        conn.commit()
    conn.close()
    return result

def init_db():
    conn, mode = get_db()
    if mode == 'pg':
        import psycopg2.extras
        cur = conn.cursor()
        cur.execute('''CREATE TABLE IF NOT EXISTS activos (
            id TEXT PRIMARY KEY,
            tipo TEXT, subtipo TEXT, marca TEXT, modelo TEXT, serie TEXT,
            estado TEXT, edificio TEXT, sala TEXT, responsable TEXT,
            fecha_compra TEXT, precio REAL, documento TEXT, vida_util INTEGER,
            observaciones TEXT, foto TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        cur.execute('''CREATE TABLE IF NOT EXISTS movimientos (
            id SERIAL PRIMARY KEY,
            activo_id TEXT, tipo TEXT, descripcion TEXT,
            usuario TEXT, fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        cur.execute('''CREATE TABLE IF NOT EXISTS usuarios (
            id SERIAL PRIMARY KEY,
            nombre TEXT, email TEXT UNIQUE, password TEXT, rol TEXT DEFAULT 'consulta'
        )''')
        cur.execute("INSERT INTO usuarios (nombre,email,password,rol) VALUES (%s,%s,%s,%s) ON CONFLICT (email) DO NOTHING",
                    ('Administrador',
                     os.environ.get('ADMIN_EMAIL','admin@colegio.cl'),
                     os.environ.get('ADMIN_PASS','admin123'),
                     'admin'))
    else:
        import sqlite3
        cur = conn.cursor()
        cur.execute('''CREATE TABLE IF NOT EXISTS activos (
            id TEXT PRIMARY KEY,
            tipo TEXT, subtipo TEXT, marca TEXT, modelo TEXT, serie TEXT,
            estado TEXT, edificio TEXT, sala TEXT, responsable TEXT,
            fecha_compra TEXT, precio REAL, documento TEXT, vida_util INTEGER,
            observaciones TEXT, foto TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )''')
        try: cur.execute("ALTER TABLE activos ADD COLUMN foto TEXT")
        except: pass
        cur.execute('''CREATE TABLE IF NOT EXISTS movimientos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            activo_id TEXT, tipo TEXT, descripcion TEXT,
            usuario TEXT, fecha TEXT DEFAULT CURRENT_TIMESTAMP
        )''')
        cur.execute('''CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT, email TEXT UNIQUE, password TEXT, rol TEXT DEFAULT 'consulta'
        )''')
        cur.execute("INSERT OR IGNORE INTO usuarios (nombre,email,password,rol) VALUES (?,?,?,?)",
                    ('Administrador',
                     os.environ.get('ADMIN_EMAIL','admin@colegio.cl'),
                     os.environ.get('ADMIN_PASS','admin123'),
                     'admin'))
    conn.commit()
    conn.close()

with app.app_context():
    init_db()

def next_id():
    year = datetime.now().year % 100
    conn, mode = get_db()
    if mode == 'pg':
        cur = conn.cursor()
        cur.execute("SELECT id FROM activos WHERE id LIKE 'AF-%'")
        rows = cur.fetchall()
    else:
        cur = conn.cursor()
        rows = cur.execute("SELECT id FROM activos WHERE id LIKE 'AF-%'").fetchall()
    conn.close()
    nums = []
    for r in rows:
        parts = (r[0] if mode == 'pg' else r['id']).split('-')
        if len(parts) == 3:
            try: nums.append(int(parts[2]))
            except: pass
    nxt = max(nums) + 1 if nums else 1000
    return f"AF-{year:02d}-{nxt}"

def db_fetchall(sql, params=()):
    conn, mode = get_db()
    if mode == 'pg':
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql.replace('?','%s'), params)
    else:
        cur = conn.cursor()
        cur.execute(sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def db_fetchone(sql, params=()):
    conn, mode = get_db()
    if mode == 'pg':
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql.replace('?','%s'), params)
    else:
        cur = conn.cursor()
        cur.execute(sql, params)
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None

def db_execute(sql, params=(), commit=True):
    conn, mode = get_db()
    if mode == 'pg':
        cur = conn.cursor()
        cur.execute(sql.replace('?','%s'), params)
    else:
        cur = conn.cursor()
        cur.execute(sql, params)
    if commit:
        conn.commit()
    conn.close()

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
        u = db_fetchone("SELECT * FROM usuarios WHERE email=? AND password=?", (email, password))
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
    return render_template('index.html', user=session['user'], rol=session['rol'], tipos=TIPOS)

@app.route('/api/activos', methods=['GET'])
@login_required
def get_activos():
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
    return jsonify(db_fetchall(sql, params))

@app.route('/api/activos/<id>', methods=['GET'])
@login_required
def get_activo(id):
    a = db_fetchone("SELECT * FROM activos WHERE id=?", (id,))
    if not a: return jsonify({'error':'No encontrado'}), 404
    movs = db_fetchall("SELECT * FROM movimientos WHERE activo_id=? ORDER BY fecha DESC", (id,))
    return jsonify({'activo': a, 'movimientos': movs})

@app.route('/api/activos', methods=['POST'])
@admin_required
def crear_activo():
    data = request.json
    aid = next_id()
    db_execute('''INSERT INTO activos
        (id,tipo,subtipo,marca,modelo,serie,estado,edificio,sala,responsable,
         fecha_compra,precio,documento,vida_util,observaciones,foto)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (aid, data.get('tipo'), data.get('subtipo'), data.get('marca'),
         data.get('modelo'), data.get('serie'), data.get('estado','Bueno'),
         data.get('edificio'), data.get('sala'), data.get('responsable'),
         data.get('fecha_compra'), data.get('precio',0), data.get('documento'),
         data.get('vida_util',4), data.get('observaciones',''), data.get('foto','')))
    db_execute("INSERT INTO movimientos (activo_id,tipo,descripcion,usuario) VALUES (?,?,?,?)",
               (aid, 'Alta', 'Activo registrado en el sistema', session['user']))
    return jsonify({'id': aid, 'ok': True})

@app.route('/api/activos/<id>', methods=['PUT'])
@admin_required
def editar_activo(id):
    data = request.json
    old = db_fetchone("SELECT * FROM activos WHERE id=?", (id,))
    if not old: return jsonify({'error':'No encontrado'}), 404
    campos = ['tipo','subtipo','marca','modelo','serie','estado','edificio','sala',
              'responsable','fecha_compra','precio','documento','vida_util','observaciones','foto']
    updates = {c: data[c] for c in campos if c in data}
    if updates:
        sets = ', '.join(f"{c}=?" for c in updates)
        db_execute(f"UPDATE activos SET {sets} WHERE id=?", list(updates.values()) + [id])
    cambios = []
    for c in ['estado','edificio','sala','responsable']:
        if c in data and str(old.get(c,'')) != str(data[c]):
            cambios.append(f"{c}: '{old.get(c)}' → '{data[c]}'")
    if cambios:
        db_execute("INSERT INTO movimientos (activo_id,tipo,descripcion,usuario) VALUES (?,?,?,?)",
                   (id, 'Edición', ' | '.join(cambios), session['user']))
    return jsonify({'ok': True})

@app.route('/api/activos/<id>', methods=['DELETE'])
@admin_required
def eliminar_activo(id):
    a = db_fetchone("SELECT id, subtipo, marca FROM activos WHERE id=?", (id,))
    if not a: return jsonify({'error':'No encontrado'}), 404
    db_execute("DELETE FROM movimientos WHERE activo_id=?", (id,))
    db_execute("DELETE FROM activos WHERE id=?", (id,))
    return jsonify({'ok': True})

@app.route('/api/activos/<id>/traslado', methods=['POST'])
@admin_required
def traslado(id):
    data = request.json
    old = db_fetchone("SELECT edificio,sala,responsable FROM activos WHERE id=?", (id,))
    db_execute("UPDATE activos SET edificio=?,sala=?,responsable=? WHERE id=?",
               (data['edificio'], data['sala'], data.get('responsable',''), id))
    desc = f"Traslado: {old['sala']} → {data['sala']} | Responsable: {data.get('responsable','—')}"
    db_execute("INSERT INTO movimientos (activo_id,tipo,descripcion,usuario) VALUES (?,?,?,?)",
               (id, 'Traslado', desc, session['user']))
    return jsonify({'ok': True})

@app.route('/api/activos/<id>/foto', methods=['POST'])
@admin_required
def subir_foto(id):
    if 'foto' not in request.files:
        return jsonify({'error': 'No se envió archivo'}), 400
    file = request.files['foto']
    ext = file.filename.rsplit('.', 1)[-1].lower()
    if ext not in {'jpg','jpeg','png','gif','webp'}:
        return jsonify({'error': 'Formato no permitido'}), 400
    data = file.read()
    if len(data) > 5 * 1024 * 1024:
        return jsonify({'error': 'Imagen muy grande (máx 5MB)'}), 400
    b64 = f"data:image/{ext};base64," + base64.b64encode(data).decode()
    db_execute("UPDATE activos SET foto=? WHERE id=?", (b64, id))
    db_execute("INSERT INTO movimientos (activo_id,tipo,descripcion,usuario) VALUES (?,?,?,?)",
               (id, 'Foto', 'Foto del activo actualizada', session['user']))
    return jsonify({'ok': True, 'foto': b64})

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
        b64 = _simple_qr_b64(id)
    return jsonify({'qr': b64, 'url': url})

def _simple_qr_b64(text):
    size, cell = 21, 10
    img_size = size * cell + 20
    seed = sum(ord(c)*(i+1) for i,c in enumerate(text))
    def dark(r,c):
        if (r<7 and c<7) or (r<7 and c>=size-7) or (r>=size-7 and c<7):
            if r==0 or r==6 or c==0 or c==6: return True
            if 2<=r<=4 and 2<=c<=4: return True
            return False
        return (seed*(r+1)*(c+1)+r*3+c*7)%4!=0
    w=h=img_size; pad=10; rgba=[]
    for y in range(h):
        for x in range(w):
            rc,cc=(y-pad)//cell,(x-pad)//cell
            if 0<=rc<size and 0<=cc<size and dark(rc,cc): rgba+=[0,0,0,255]
            else: rgba+=[255,255,255,255]
    def chunk(name,data):
        c=zlib.crc32(name+data)&0xffffffff
        return struct.pack('>I',len(data))+name+data+struct.pack('>I',c)
    rows=b''
    for y in range(h):
        rows+=bytes([0])+bytes(rgba[y*w*4:(y+1)*w*4])
    comp=zlib.compress(rows,9)
    ihdr=struct.pack('>II',w,h)+bytes([8,2,0,0,0])
    png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',ihdr)+chunk(b'IDAT',comp)+chunk(b'IEND',b'')
    return base64.b64encode(png).decode()

@app.route('/ficha/<id>')
def ficha_publica(id):
    a = db_fetchone("SELECT * FROM activos WHERE id=?", (id,))
    if not a: return "Activo no encontrado", 404
    return render_template('ficha_publica.html', a=a)

@app.route('/api/stats')
@login_required
def stats():
    total = db_fetchone("SELECT COUNT(*) as n FROM activos")['n']
    buenos = db_fetchone("SELECT COUNT(*) as n FROM activos WHERE estado='Bueno'")['n']
    malos = db_fetchone("SELECT COUNT(*) as n FROM activos WHERE estado='Malo'")['n']
    valor = db_fetchone("SELECT COALESCE(SUM(precio),0) as s FROM activos")['s']
    por_edificio = db_fetchall("SELECT edificio, COUNT(*) as n FROM activos GROUP BY edificio")
    return jsonify({'total':total,'buenos':buenos,'malos':malos,
                    'valor':valor,'por_edificio':por_edificio})

@app.route('/api/export/excel')
@login_required
def export_excel():
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    rows = db_fetchall("SELECT * FROM activos ORDER BY id")
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Activos Fijos"
    headers = ['ID Activo','Tipo','Subtipo','Marca','Modelo','N° Serie','Estado',
               'Edificio','Sala','Responsable','Fecha Compra','Precio','Documento','Vida Útil','Observaciones']
    keys = ['id','tipo','subtipo','marca','modelo','serie','estado','edificio','sala',
            'responsable','fecha_compra','precio','documento','vida_util','observaciones']
    for col,h in enumerate(headers,1):
        cell=ws.cell(row=1,column=col,value=h)
        cell.font=Font(bold=True,color='FFFFFF')
        cell.fill=PatternFill('solid',start_color='1F3864',fgColor='1F3864')
        cell.alignment=Alignment(horizontal='center')
        ws.column_dimensions[ws.cell(row=1,column=col).column_letter].width=18
    for ri,row in enumerate(rows,2):
        for col,key in enumerate(keys,1):
            ws.cell(row=ri,column=col,value=row.get(key,''))
    buf=io.BytesIO(); wb.save(buf); buf.seek(0)
    return send_file(buf,download_name='activos_fijos.xlsx',as_attachment=True,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

if __name__ == '__main__':
    init_db()
    app.run(debug=False,host='0.0.0.0',port=int(os.environ.get('PORT',5000)))
