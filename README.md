# EncuestaCLARO

Plataforma Flask para crear, responder y consultar encuestas con MySQL.

## Ejecutar en Windows
1. Crea un entorno: `py -3.14 -m venv venv`
2. Instala: `venv\Scripts\python.exe -m pip install -r requirements.txt`
3. Configura MySQL en `conexion.py` o mediante variables `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`, `DB_PORT`.
4. Ejecuta: `venv\Scripts\python.exe app.py`
5. Abre `http://127.0.0.1:5000`.

La carpeta `venv` no se incluye en esta versión distribuible; se recomienda crearla localmente.
