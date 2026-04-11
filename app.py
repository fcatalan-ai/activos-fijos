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

# SII vida util por tipo
VIDA_UTIL_SII = {
    'Equipamiento Tecnológico': 6,
    'Equipamiento Audiovisual': 7,
    'Equipamiento Deportivo':   5,
    'Mobiliario':               7,
    'Muebles y Útiles':         7,
    'Otro':                     7,
}

def get_db():
    if DATABASE_URL:
        import psycopg2, psycopg2.extras
        return psycopg2.connect(DATABASE_URL), 'pg'
    import sqlite3
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'activos.db')
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn, 'sqlite'

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
            nombre TEXT, email TEXT UNIQUE, password TEXT, rol TEXT DEFAULT \'consulta\'
        )''')
        cur.execute("INSERT INTO usuarios (nombre,email,password,rol) VALUES (%s,%s,%s,%s) ON CONFLICT (email) DO NOTHING",
                    ('Administrador', os.environ.get('ADMIN_EMAIL','admin@colegio.cl'),
                     os.environ.get('ADMIN_PASS','admin123'), 'admin'))
    else:
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
            nombre TEXT, email TEXT UNIQUE, password TEXT, rol TEXT DEFAULT \'consulta\'
        )''')
        cur.execute("INSERT OR IGNORE INTO usuarios (nombre,email,password,rol) VALUES (?,?,?,?)",
                    ('Administrador', os.environ.get('ADMIN_EMAIL','admin@colegio.cl'),
                     os.environ.get('ADMIN_PASS','admin123'), 'admin'))
    conn.commit()
    conn.close()

with app.app_context():
    init_db()

def next_id():
    year = datetime.now().year % 100
    rows = db_fetchall("SELECT id FROM activos WHERE id LIKE 'AF-%'")
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
        if 'user' not in session: return redirect('/login')
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user' not in session: return redirect('/login')
        if session.get('rol') != 'admin': return jsonify({'error':'Sin permisos'}), 403
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
        p = f'%{q}%'; params += [p,p,p,p,p]
    if tipo:     sql += " AND tipo=?";     params.append(tipo)
    if estado:   sql += " AND estado=?";   params.append(estado)
    if edificio: sql += " AND edificio=?"; params.append(edificio)
    sql += " ORDER BY id DESC"
    return jsonify(db_fetchall(sql, params))

@app.route('/api/activos/<id>', methods=['GET'])
@login_required
def get_activo(id):
    a = db_fetchone("SELECT * FROM activos WHERE id=?", (id,))
    if not a: return jsonify({'error':'No encontrado'}), 404
    movs = db_fetchall("SELECT * FROM movimientos WHERE activo_id=? ORDER BY fecha DESC", (id,))
    # Calcular depreciacion
    dep = calcular_depreciacion(a)
    return jsonify({'activo': a, 'movimientos': movs, 'depreciacion': dep})

def calcular_depreciacion(a):
    try:
        if not a.get('fecha_compra') or not a.get('precio'):
            return None
        fecha_str = str(a['fecha_compra'])
        # Intentar parsear fecha en varios formatos
        for fmt in ['%d-%m-%Y','%Y-%m-%d','%d/%m/%Y']:
            try:
                fecha = datetime.strptime(fecha_str[:10], fmt)
                break
            except: fecha = None
        if not fecha: return None

        precio_original = float(a['precio'])
        if precio_original <= 0: return None

        tipo = a.get('tipo','Otro')
        vida_util = int(a.get('vida_util') or VIDA_UTIL_SII.get(tipo, 7))
        tasa_anual = 1.0 / vida_util

        hoy = datetime.now()
        anos_transcurridos = (hoy - fecha).days / 365.25
        valor_residual = precio_original * 0.10  # 10% valor residual SII

        depreciacion_acumulada = min(precio_original - valor_residual,
                                     (precio_original - valor_residual) * tasa_anual * anos_transcurridos)
        valor_actual = max(valor_residual, precio_original - depreciacion_acumulada)
        porcentaje_dep = min(100, (depreciacion_acumulada / (precio_original - valor_residual)) * 100) if precio_original > valor_residual else 100

        fecha_termino = datetime(fecha.year + vida_util, fecha.month, fecha.day)
        anos_restantes = max(0, (fecha_termino - hoy).days / 365.25)

        return {
            'precio_original':      round(precio_original),
            'valor_actual':         round(valor_actual),
            'valor_residual':       round(valor_residual),
            'depreciacion_acum':    round(depreciacion_acumulada),
            'porcentaje_dep':       round(porcentaje_dep, 1),
            'anos_transcurridos':   round(anos_transcurridos, 1),
            'anos_restantes':       round(anos_restantes, 1),
            'vida_util':            vida_util,
            'tasa_anual':           round(tasa_anual * 100, 2),
            'fecha_termino':        fecha_termino.strftime('%d-%m-%Y'),
            'estado_dep':           'Depreciado' if porcentaje_dep >= 100 else
                                    'Crítico' if porcentaje_dep >= 80 else
                                    'Avanzado' if porcentaje_dep >= 50 else 'Normal',
        }
    except Exception as e:
        return None

@app.route('/api/activos', methods=['POST'])
@admin_required
def crear_activo():
    data = request.json
    aid = next_id()
    vida = data.get('vida_util') or VIDA_UTIL_SII.get(data.get('tipo','Otro'), 7)
    db_execute('''INSERT INTO activos
        (id,tipo,subtipo,marca,modelo,serie,estado,edificio,sala,responsable,
         fecha_compra,precio,documento,vida_util,observaciones,foto)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (aid, data.get('tipo'), data.get('subtipo'), data.get('marca'),
         data.get('modelo'), data.get('serie'), data.get('estado','Bueno'),
         data.get('edificio'), data.get('sala'), data.get('responsable'),
         data.get('fecha_compra'), data.get('precio',0), data.get('documento'),
         vida, data.get('observaciones',''), data.get('foto','')))
    db_execute("INSERT INTO movimientos (activo_id,tipo,descripcion,usuario) VALUES (?,?,?,?)",
               (aid,'Alta','Activo registrado en el sistema',session['user']))
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
        db_execute(f"UPDATE activos SET {sets} WHERE id=?", list(updates.values())+[id])
    cambios = []
    for c in ['estado','edificio','sala','responsable']:
        if c in data and str(old.get(c,'')) != str(data[c]):
            cambios.append(f"{c}: '{old.get(c)}' → '{data[c]}'")
    if cambios:
        db_execute("INSERT INTO movimientos (activo_id,tipo,descripcion,usuario) VALUES (?,?,?,?)",
                   (id,'Edición',' | '.join(cambios),session['user']))
    return jsonify({'ok': True})

@app.route('/api/activos/<id>', methods=['DELETE'])
@admin_required
def eliminar_activo(id):
    if not db_fetchone("SELECT id FROM activos WHERE id=?", (id,)):
        return jsonify({'error':'No encontrado'}), 404
    db_execute("DELETE FROM movimientos WHERE activo_id=?", (id,))
    db_execute("DELETE FROM activos WHERE id=?", (id,))
    return jsonify({'ok': True})

@app.route('/api/activos/<id>/traslado', methods=['POST'])
@admin_required
def traslado(id):
    data = request.json
    old = db_fetchone("SELECT edificio,sala,responsable FROM activos WHERE id=?", (id,))
    db_execute("UPDATE activos SET edificio=?,sala=?,responsable=? WHERE id=?",
               (data['edificio'],data['sala'],data.get('responsable',''),id))
    desc = f"Traslado: {old['sala']} → {data['sala']} | Responsable: {data.get('responsable','—')}"
    db_execute("INSERT INTO movimientos (activo_id,tipo,descripcion,usuario) VALUES (?,?,?,?)",
               (id,'Traslado',desc,session['user']))
    return jsonify({'ok': True})

@app.route('/api/activos/<id>/foto', methods=['POST'])
@admin_required
def subir_foto(id):
    if 'foto' not in request.files: return jsonify({'error':'No se envió archivo'}), 400
    file = request.files['foto']
    ext = file.filename.rsplit('.',1)[-1].lower()
    if ext not in {'jpg','jpeg','png','gif','webp'}: return jsonify({'error':'Formato no permitido'}), 400
    data = file.read()
    if len(data) > 5*1024*1024: return jsonify({'error':'Imagen muy grande (máx 5MB)'}), 400
    b64 = f"data:image/{ext};base64,"+base64.b64encode(data).decode()
    db_execute("UPDATE activos SET foto=? WHERE id=?", (b64,id))
    db_execute("INSERT INTO movimientos (activo_id,tipo,descripcion,usuario) VALUES (?,?,?,?)",
               (id,'Foto','Foto del activo actualizada',session['user']))
    return jsonify({'ok':True,'foto':b64})


@app.route('/api/debug-excel', methods=['POST'])
@admin_required
def debug_excel():
    if 'archivo' not in request.files:
        return jsonify({'error':'No archivo'}), 400
    file = request.files['archivo']
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(file.read()), data_only=True)
        hojas = wb.sheetnames
        ws = None
        for name in wb.sheetnames:
            nu = name.upper()
            if 'CARGA' in nu or ('ACTIVO' in nu and 'INSTRUC' not in nu):
                ws = wb[name]; break
        if ws is None:
            ws = wb.worksheets[1] if len(wb.worksheets) > 1 else wb.active
        
        # Leer primeras 6 filas para debug
        preview = []
        for row in range(1, 7):
            fila = []
            for col in range(1, min(ws.max_column+1, 16)):
                v = ws.cell(row=row, column=col).value
                fila.append(str(v) if v is not None else '')
            preview.append(fila)
        
        return jsonify({
            'hojas': hojas,
            'hoja_usada': ws.title,
            'max_row': ws.max_row,
            'max_col': ws.max_column,
            'preview_filas_1_6': preview
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/importar', methods=['POST'])
@admin_required
def importar_excel():
    if 'archivo' not in request.files:
        return jsonify({'error':'No se envio archivo'}), 400
    file = request.files['archivo']
    if not file.filename.lower().endswith(('.xlsx','.xls')):
        return jsonify({'error':'Solo se aceptan archivos Excel (.xlsx)'}), 400
    try:
        import openpyxl
        data_bytes = file.read()
        wb = openpyxl.load_workbook(io.BytesIO(data_bytes), data_only=True)

        # Buscar la hoja correcta
        ws = None
        for name in wb.sheetnames:
            nu = name.upper()
            if 'CARGA' in nu or ('ACTIVO' in nu and 'INSTRUC' not in nu):
                ws = wb[name]; break
        if ws is None:
            ws = wb.worksheets[0] if len(wb.worksheets)==1 else (wb.worksheets[1] if len(wb.worksheets)>1 else wb.active)

        # Detectar fila de encabezados (buscar en filas 1-5)
        header_row = None
        col_map = {}
        BUSCAR = {
            'tipo':['tipo'],
            'subtipo':['subtipo'],
            'marca':['marca'],
            'modelo':['modelo'],
            'serie':['serie','n serie','num'],
            'estado':['estado'],
            'edificio':['edificio'],
            'sala':['sala','dependencia'],
            'responsable':['responsable'],
            'fecha_compra':['fecha'],
            'precio':['precio'],
            'documento':['documento','factura','doc'],
            'vida_util':['vida','util'],
            'observaciones':['observacion','obs'],
        }
        for fila in range(1, 6):
            for col in range(1, ws.max_column+1):
                v = ws.cell(row=fila, column=col).value
                if not v: continue
                vs = str(v).lower().replace('\n',' ').replace('*','').strip()
                for campo, claves in BUSCAR.items():
                    if campo not in col_map:
                        for clave in claves:
                            if clave in vs:
                                col_map[campo] = col
                                header_row = fila
                                break
        if not header_row:
            return jsonify({'error':'No se encontraron encabezados en el archivo. Asegurate de usar la plantilla oficial.'}), 400

        data_start = header_row + 1

        def get_val(row_num, campo):
            col = col_map.get(campo)
            if not col: return ''
            v = ws.cell(row=row_num, column=col).value
            if v is None: return ''
            return str(v).strip()

        creados = 0
        omitidos = 0
        errores = []

        for row_num in range(data_start, ws.max_row + 1):
            tipo     = get_val(row_num, 'tipo')
            subtipo  = get_val(row_num, 'subtipo')
            edificio = get_val(row_num, 'edificio')

            # Fila vacia
            if not tipo and not subtipo:
                omitidos += 1
                continue
            # Fila de ejemplo
            if any(x in (tipo+subtipo).lower() for x in ['ejemplo','example','muestra','test']):
                omitidos += 1
                continue
            # Faltan obligatorios
            if not tipo or not subtipo or not edificio:
                errores.append(f"Fila {row_num}: faltan campos obligatorios (Tipo={tipo!r}, Subtipo={subtipo!r}, Edificio={edificio!r})")
                continue

            try:
                estado = get_val(row_num, 'estado') or 'Bueno'
                if estado not in ('Bueno','Regular','Malo'): estado = 'Bueno'

                precio_raw = get_val(row_num, 'precio')
                try:
                    precio = float(str(precio_raw).replace('.','').replace(',','.').replace('$','').strip()) if precio_raw else 0
                except: precio = 0

                vida_raw = get_val(row_num, 'vida_util')
                try: vida = int(float(vida_raw)) if vida_raw else VIDA_UTIL_SII.get(tipo, 7)
                except: vida = VIDA_UTIL_SII.get(tipo, 7)

                aid = next_id()
                marca      = get_val(row_num,'marca')
                modelo     = get_val(row_num,'modelo')
                serie      = get_val(row_num,'serie')
                sala       = get_val(row_num,'sala')
                responsable= get_val(row_num,'responsable')
                fecha      = get_val(row_num,'fecha_compra')
                documento  = get_val(row_num,'documento')
                obs        = get_val(row_num,'observaciones')
                usuario    = session['user']

                conn2, mode2 = get_db()
                cur2 = conn2.cursor()
                if mode2 == 'pg':
                    cur2.execute(
                        "INSERT INTO activos (id,tipo,subtipo,marca,modelo,serie,estado,edificio,sala,responsable,fecha_compra,precio,documento,vida_util,observaciones,foto) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (aid,tipo,subtipo,marca,modelo,serie,estado,edificio,sala,responsable,fecha,precio,documento,vida,obs,'')
                    )
                    cur2.execute(
                        "INSERT INTO movimientos (activo_id,tipo,descripcion,usuario) VALUES (%s,%s,%s,%s)",
                        (aid,'Alta',f'Importado desde Excel fila {row_num}',usuario)
                    )
                else:
                    cur2.execute(
                        "INSERT INTO activos (id,tipo,subtipo,marca,modelo,serie,estado,edificio,sala,responsable,fecha_compra,precio,documento,vida_util,observaciones,foto) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (aid,tipo,subtipo,marca,modelo,serie,estado,edificio,sala,responsable,fecha,precio,documento,vida,obs,'')
                    )
                    cur2.execute(
                        "INSERT INTO movimientos (activo_id,tipo,descripcion,usuario) VALUES (?,?,?,?)",
                        (aid,'Alta',f'Importado desde Excel fila {row_num}',usuario)
                    )
                conn2.commit()
                conn2.close()
                creados += 1
            except Exception as e:
                errores.append(f"Fila {row_num}: {str(e)}")

        msg = f"{creados} activos importados"
        if omitidos: msg += f", {omitidos} filas omitidas (vacias o ejemplos)"
        return jsonify({'ok':True,'creados':creados,'errores':errores,'mensaje':msg})

    except Exception as e:
        return jsonify({'error':f'Error procesando archivo: {str(e)}'}), 500

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
    except:
        b64 = _simple_qr_b64(id)
    return jsonify({'qr':b64,'url':url})

def _simple_qr_b64(text):
    size,cell=21,10; img_size=size*cell+20
    seed=sum(ord(c)*(i+1) for i,c in enumerate(text))
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
    for y in range(h): rows+=bytes([0])+bytes(rgba[y*w*4:(y+1)*w*4])
    comp=zlib.compress(rows,9)
    ihdr=struct.pack('>II',w,h)+bytes([8,2,0,0,0])
    return base64.b64encode(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',ihdr)+chunk(b'IDAT',comp)+chunk(b'IEND',b'')).decode()

@app.route('/ficha/<id>')
def ficha_publica(id):
    a = db_fetchone("SELECT * FROM activos WHERE id=?", (id,))
    if not a: return "Activo no encontrado", 404
    dep = calcular_depreciacion(a)
    return render_template('ficha_publica.html', a=a, dep=dep)

@app.route('/api/stats')
@login_required
def stats():
    total   = db_fetchone("SELECT COUNT(*) as n FROM activos")['n']
    buenos  = db_fetchone("SELECT COUNT(*) as n FROM activos WHERE estado='Bueno'")['n']
    malos   = db_fetchone("SELECT COUNT(*) as n FROM activos WHERE estado='Malo'")['n']
    valor   = db_fetchone("SELECT COALESCE(SUM(precio),0) as s FROM activos")['s']
    por_edificio = db_fetchall("SELECT edificio, COUNT(*) as n FROM activos GROUP BY edificio")
    return jsonify({'total':total,'buenos':buenos,'malos':malos,'valor':valor,'por_edificio':por_edificio})

@app.route('/api/export/excel')
@login_required
def export_excel():
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    rows = db_fetchall("SELECT * FROM activos ORDER BY id")
    wb = openpyxl.Workbook(); ws = wb.active; ws.title="Activos Fijos"
    headers=['ID Activo','Tipo','Subtipo','Marca','Modelo','N° Serie','Estado',
             'Edificio','Sala','Responsable','Fecha Compra','Precio','Documento','Vida Útil','Observaciones']
    keys=['id','tipo','subtipo','marca','modelo','serie','estado','edificio','sala',
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

if __name__=='__main__':
    init_db()
    app.run(debug=False,host='0.0.0.0',port=int(os.environ.get('PORT',5000)))
