import os
import re
from collections import Counter
from functools import wraps

from flask import Flask, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from conexion import obtener_conexion

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "encuesta-claro-cambia-esta-clave")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "0") == "1",
)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "id" not in session:
            flash("Inicia sesión para acceder a esta sección.", "warning")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def fetchall(sql, params=()):
    conexion = obtener_conexion()
    try:
        with conexion.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()
    finally:
        conexion.close()


def fetchone(sql, params=()):
    conexion = obtener_conexion()
    try:
        with conexion.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchone()
    finally:
        conexion.close()


def survey_columns():
    """Detecta columnas opcionales para mantener compatibilidad con la BD actual."""
    try:
        rows = fetchall("SHOW COLUMNS FROM encuestas")
        return {row["Field"] for row in rows}
    except Exception:
        return {"id", "titulo"}


def normalize_options(raw):
    return [item.strip() for item in (raw or "").split(",") if item.strip()]


@app.context_processor
def inject_globals():
    return {"current_year": 2026}


@app.route("/")
@app.route("/inicio")
def inicio():
    encuestas = fetchall("SELECT * FROM encuestas ORDER BY id DESC")
    return render_template("index_logged.html" if "id" in session else "index.html", encuestas=encuestas[:6])


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        correo = request.form.get("correo", "").strip().lower()
        contrasena = request.form.get("contrasena", "")
        if not correo or not contrasena:
            flash("Completa el correo y la contraseña.", "warning")
            return render_template("login.html")

        user = fetchone("SELECT * FROM usuarios WHERE correo = %s", (correo,))
        valid = False
        if user:
            try:
                valid = check_password_hash(user["contrasena"], contrasena)
            except (ValueError, TypeError):
                valid = user["contrasena"] == contrasena

        if not valid:
            flash("Correo o contraseña incorrectos.", "danger")
            return render_template("login.html")

        session.clear()
        session["id"] = user["id"]
        session["usuario"] = user["nombre_usuario"]
        session["correo"] = user["correo"]
        flash(f"Bienvenido, {user['nombre_usuario']}.", "success")
        next_url = request.args.get("next")
        if next_url and next_url.startswith("/"):
            return redirect(next_url)
        return redirect(url_for("inicio"))

    return render_template("login.html")


@app.route("/registro", methods=["GET", "POST"])
def registro():
    if request.method == "POST":
        correo = request.form.get("correo", "").strip().lower()
        usuario = request.form.get("usuario", "").strip()
        contrasena = request.form.get("contrasena", "")
        confirmar = request.form.get("confirmar_contrasena", "")

        if not correo or not usuario or not contrasena:
            flash("Todos los campos son obligatorios.", "warning")
            return render_template("registro.html")
        if "@" not in correo:
            flash("Ingresa un correo electrónico válido.", "warning")
            return render_template("registro.html")
        if len(contrasena) < 6:
            flash("La contraseña debe tener al menos 6 caracteres.", "warning")
            return render_template("registro.html")
        if confirmar and contrasena != confirmar:
            flash("Las contraseñas no coinciden.", "warning")
            return render_template("registro.html")

        conexion = obtener_conexion()
        try:
            with conexion.cursor() as cursor:
                cursor.execute("SELECT id FROM usuarios WHERE correo = %s", (correo,))
                if cursor.fetchone():
                    flash("Ese correo ya está registrado.", "warning")
                    return render_template("registro.html")
                hashed = generate_password_hash(contrasena)
                cursor.execute(
                    "INSERT INTO usuarios (correo, contrasena, nombre_usuario) VALUES (%s, %s, %s)",
                    (correo, hashed, usuario),
                )
                user_id = cursor.lastrowid
            conexion.commit()
        except Exception as exc:
            conexion.rollback()
            app.logger.exception("Error registrando usuario: %s", exc)
            flash("No fue posible crear la cuenta. Revisa la conexión con MySQL.", "danger")
            return render_template("registro.html")
        finally:
            conexion.close()

        session.clear()
        session["id"] = user_id
        session["usuario"] = usuario
        session["correo"] = correo
        flash("Cuenta creada correctamente.", "success")
        return redirect(url_for("inicio"))

    return render_template("registro.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Sesión cerrada correctamente.", "success")
    return redirect(url_for("inicio"))


@app.route("/encuestas")
def encuestas():
    lista_encuestas = fetchall("SELECT * FROM encuestas ORDER BY id DESC")
    return render_template("encuestas.html", encuestas=lista_encuestas)


@app.route("/crear_encuesta", methods=["GET", "POST"])
@login_required
def crear_encuesta():
    if request.method == "POST":
        titulo = request.form.get("titulo", "").strip()
        descripcion = request.form.get("descripcion", "").strip()
        texto_pregunta = request.form.get("pregunta", "").strip()
        tipo_pregunta = request.form.get("tipo_pregunta", "abierta")
        opciones = request.form.get("opciones", "").strip()

        if not titulo or not texto_pregunta:
            flash("El título y la primera pregunta son obligatorios.", "warning")
            return render_template("crear_encuesta.html")
        if tipo_pregunta == "opcion_multiple" and not normalize_options(opciones):
            flash("Agrega al menos dos opciones para la pregunta de selección.", "warning")
            return render_template("crear_encuesta.html")

        conexion = obtener_conexion()
        try:
            cols = survey_columns()
            with conexion.cursor() as cursor:
                if "descripcion" in cols:
                    cursor.execute("INSERT INTO encuestas (titulo, descripcion) VALUES (%s, %s)", (titulo, descripcion))
                else:
                    cursor.execute("INSERT INTO encuestas (titulo) VALUES (%s)", (titulo,))
                encuesta_id = cursor.lastrowid
                cursor.execute(
                    "INSERT INTO preguntas (encuesta_id, texto_pregunta, tipo, opciones) VALUES (%s, %s, %s, %s)",
                    (encuesta_id, texto_pregunta, tipo_pregunta, ",".join(normalize_options(opciones))),
                )
            conexion.commit()
            flash("Encuesta creada. Ahora puedes agregar más preguntas.", "success")
        except Exception as exc:
            conexion.rollback()
            app.logger.exception("Error creando encuesta: %s", exc)
            flash("No fue posible crear la encuesta. Revisa la base de datos.", "danger")
            return render_template("crear_encuesta.html")
        finally:
            conexion.close()
        return redirect(url_for("agregar_pregunta", encuesta_id=encuesta_id))

    return render_template("crear_encuesta.html")


@app.route("/agregar_pregunta/<int:encuesta_id>", methods=["GET", "POST"])
@login_required
def agregar_pregunta(encuesta_id):
    encuesta = fetchone("SELECT * FROM encuestas WHERE id = %s", (encuesta_id,))
    if not encuesta:
        flash("La encuesta no existe.", "danger")
        return redirect(url_for("encuestas"))

    if request.method == "POST":
        texto_pregunta = request.form.get("pregunta", "").strip()
        tipo_pregunta = request.form.get("tipo_pregunta", "abierta")
        opciones = request.form.get("opciones", "").strip()
        if not texto_pregunta:
            flash("Escribe el texto de la pregunta.", "warning")
        elif tipo_pregunta == "opcion_multiple" and len(normalize_options(opciones)) < 2:
            flash("Una pregunta de selección necesita al menos dos opciones.", "warning")
        else:
            conexion = obtener_conexion()
            try:
                with conexion.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO preguntas (encuesta_id, texto_pregunta, tipo, opciones) VALUES (%s, %s, %s, %s)",
                        (encuesta_id, texto_pregunta, tipo_pregunta, ",".join(normalize_options(opciones))),
                    )
                conexion.commit()
                flash("Pregunta agregada correctamente.", "success")
            except Exception as exc:
                conexion.rollback()
                app.logger.exception("Error agregando pregunta: %s", exc)
                flash("No fue posible agregar la pregunta.", "danger")
            finally:
                conexion.close()
        return redirect(url_for("agregar_pregunta", encuesta_id=encuesta_id))

    preguntas = fetchall("SELECT * FROM preguntas WHERE encuesta_id = %s ORDER BY id ASC", (encuesta_id,))
    return render_template("agregar_pregunta.html", encuesta=encuesta, preguntas=preguntas)


@app.route("/encuesta/<int:encuesta_id>", methods=["GET", "POST"])
def responder_encuesta(encuesta_id):
    encuesta = fetchone("SELECT * FROM encuestas WHERE id = %s", (encuesta_id,))
    if not encuesta:
        flash("La encuesta solicitada no existe.", "danger")
        return redirect(url_for("encuestas"))

    preguntas = fetchall("SELECT * FROM preguntas WHERE encuesta_id = %s ORDER BY id ASC", (encuesta_id,))
    if request.method == "POST":
        if not preguntas:
            flash("Esta encuesta todavía no tiene preguntas.", "warning")
            return redirect(url_for("encuestas"))

        usuario_id = session.get("id")
        conexion = obtener_conexion()
        try:
            with conexion.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO envios_respuestas (encuesta_id, usuario_id) VALUES (%s, %s)",
                    (encuesta_id, usuario_id),
                )
                envio_id = cursor.lastrowid
                for pregunta in preguntas:
                    clave = f"pregunta_{pregunta['id']}"
                    valor = request.form.get(clave, "").strip()
                    if not valor:
                        raise ValueError(f"Falta responder la pregunta {pregunta['id']}")
                    cursor.execute(
                        "INSERT INTO detalle_respuestas (envio_id, pregunta_id, texto_respuesta) VALUES (%s, %s, %s)",
                        (envio_id, pregunta["id"], valor),
                    )
            conexion.commit()
            flash("Tus respuestas fueron registradas correctamente. Gracias por participar.", "success")
        except ValueError as exc:
            conexion.rollback()
            flash(str(exc), "warning")
        except Exception as exc:
            conexion.rollback()
            app.logger.exception("Error guardando respuestas: %s", exc)
            flash("No fue posible guardar las respuestas.", "danger")
        finally:
            conexion.close()
        return redirect(url_for("encuestas"))

    return render_template("responder_encuesta.html", encuesta=encuesta, preguntas=preguntas)


@app.route("/resultados")
@app.route("/reportes")
@login_required
def reportes():
    encuestas = fetchall("SELECT * FROM encuestas ORDER BY id DESC")
    return render_template("reportes.html", encuestas=encuestas)



STOPWORDS_ES = {
    "a","al","algo","algunas","algunos","ante","antes","como","con","contra","cual","cuando",
    "de","del","desde","donde","dos","el","él","ella","ellas","ellos","en","entre","era","es",
    "esa","esas","ese","eso","esos","esta","estas","este","esto","estos","ha","hace","hacia",
    "hasta","hay","la","las","le","les","lo","los","más","me","mi","mis","muy","no","nos",
    "o","para","pero","por","que","qué","se","si","sí","sin","sobre","son","su","sus","también",
    "te","tiene","tienen","todo","todos","tu","tus","un","una","unas","uno","unos","y","ya"
}

def analyze_open_text(texts, limit=8):
    """Obtiene palabras frecuentes de respuestas abiertas, sin contar palabras vacías."""
    counter = Counter()
    for text in texts:
        words = re.findall(r"[a-záéíóúüñ]{3,}", (text or "").lower())
        for word in words:
            if word not in STOPWORDS_ES:
                counter[word] += 1
    return [{"word": word, "count": count} for word, count in counter.most_common(limit)]

@app.route("/resultados/<int:encuesta_id>")
@login_required
def ver_resultados(encuesta_id):
    encuesta = fetchone("SELECT * FROM encuestas WHERE id = %s", (encuesta_id,))
    if not encuesta:
        flash("La encuesta no existe.", "danger")
        return redirect(url_for("reportes"))

    preguntas = fetchall(
        "SELECT * FROM preguntas WHERE encuesta_id = %s ORDER BY id ASC",
        (encuesta_id,),
    )

    resultados = fetchall(
        """
        SELECT d.pregunta_id, p.texto_pregunta, p.tipo, p.opciones,
               d.texto_respuesta, e.fecha
        FROM detalle_respuestas d
        JOIN preguntas p ON d.pregunta_id = p.id
        JOIN envios_respuestas e ON d.envio_id = e.id
        WHERE e.encuesta_id = %s
        ORDER BY e.fecha DESC, p.id ASC
        """,
        (encuesta_id,),
    )

    total_respuestas = int(fetchone(
        "SELECT COUNT(*) AS total FROM envios_respuestas WHERE encuesta_id = %s",
        (encuesta_id,),
    )["total"])

    # Una fila por pregunta, preparada para las gráficas y las métricas.
    grouped = []
    total_answer_cells = 0
    question_labels = []
    question_completion = []
    chart_data = []

    for index, pregunta in enumerate(preguntas, start=1):
        rows = [r for r in resultados if r["pregunta_id"] == pregunta["id"]]
        total = len(rows)
        total_answer_cells += total
        counts = Counter((r["texto_respuesta"] or "").strip() for r in rows)

        tipo = (pregunta.get("tipo") or "abierta").lower()
        is_choice = tipo in {"opcion_multiple", "opcion", "multiple"}
        options = normalize_options(pregunta.get("opciones", ""))

        if is_choice and options:
            # Conserva las opciones de la pregunta, incluso si alguna obtuvo 0.
            ordered = [(option, int(counts.get(option, 0))) for option in options]
            # Si existe alguna respuesta que no coincide con las opciones actuales, también se muestra.
            extras = [(answer, count) for answer, count in counts.items() if answer and answer not in options]
            ordered.extend(sorted(extras, key=lambda x: (-x[1], x[0])))
            counts_list = ordered
            open_words = []
        else:
            counts_list = sorted(
                [(answer, count) for answer, count in counts.items() if answer],
                key=lambda x: (-x[1], x[0]),
            )
            open_words = analyze_open_text([r["texto_respuesta"] for r in rows])

        pct = round((total / total_respuestas) * 100, 1) if total_respuestas else 0
        question_labels.append(f"P{index}")
        question_completion.append(pct)

        chart_data.append({
            "id": pregunta["id"],
            "number": index,
            "question": pregunta["texto_pregunta"],
            "type": tipo,
            "is_choice": is_choice,
            "total": total,
            "completion": pct,
            "labels": [a for a, _ in counts_list],
            "values": [int(c) for _, c in counts_list],
            "words": open_words,
        })

        grouped.append({
            "pregunta": pregunta,
            "total": total,
            "counts": counts_list,
            "open_words": open_words,
            "completion": pct,
            "is_choice": is_choice,
        })

    # Tendencia del número de envíos por día.
    daily_rows = fetchall(
        """
        SELECT DATE(fecha) AS dia, COUNT(*) AS total
        FROM envios_respuestas
        WHERE encuesta_id = %s
        GROUP BY DATE(fecha)
        ORDER BY DATE(fecha) ASC
        """,
        (encuesta_id,),
    )
    daily_labels = [
        row["dia"].strftime("%d/%m/%Y") if hasattr(row["dia"], "strftime") else str(row["dia"])
        for row in daily_rows
    ]
    daily_values = [int(row["total"]) for row in daily_rows]

    completion_avg = round(
        (sum(question_completion) / len(question_completion)), 1
    ) if question_completion else 0

    return render_template(
        "resultados.html",
        encuesta=encuesta,
        resultados=resultados,
        preguntas_resumen=grouped,
        total_respuestas=total_respuestas,
        total_preguntas=len(preguntas),
        total_respuestas_individuales=len(resultados),
        promedio_completitud=completion_avg,
        question_labels=question_labels,
        question_completion=question_completion,
        daily_labels=daily_labels,
        daily_values=daily_values,
        chart_data=chart_data,
    )

# Compatibilidad con plantillas/proyectos anteriores.
@app.route("/consultar_encuestas")
def consultar_encuestas():
    return redirect(url_for("encuestas"))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
