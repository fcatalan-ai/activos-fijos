# Sistema de Activos Fijos — Colegio

App web para control de inventario de activos fijos con QR, código de barras, historial de movimientos y exportación a Excel.

## Instrucciones para subir a Render.com

### Paso 1 — Subir a GitHub
1. Ve a https://github.com y crea una cuenta si no tienes
2. Crea un repositorio nuevo llamado `activos-fijos`
3. Sube todos los archivos de esta carpeta

### Paso 2 — Conectar con Render
1. Ve a https://render.com y crea una cuenta gratuita
2. Haz clic en "New +" → "Web Service"
3. Conecta tu repositorio de GitHub
4. Render detectará el `render.yaml` automáticamente
5. Haz clic en "Create Web Service"

### Paso 3 — Configurar variables de entorno
En Render, ve a Environment y configura:
- `ADMIN_EMAIL` → tu email de administrador
- `ADMIN_PASS` → tu contraseña de administrador
- `SECRET_KEY` → cualquier texto largo aleatorio

### Paso 4 — Listo
Tu app estará disponible en: `https://activos-fijos-colegio.onrender.com`

## Funcionalidades
- Login con roles (Admin / Consulta)
- Registro completo de activos con todos los campos
- Búsqueda y filtros por tipo, estado y edificio
- Ficha individual por activo
- QR descargable que abre ficha en celular
- Código de barras compatible con pistola lectora
- Historial de movimientos y traslados
- Exportación a Excel
- Página pública de ficha (accesible por QR sin login)

## Credenciales por defecto
- Email: admin@colegio.cl
- Password: admin123
⚠️ Cambia la contraseña en las variables de entorno de Render antes de usar en producción.
