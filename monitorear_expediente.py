"""
Monitorea la Lista de Acuerdos de ADISON (Poder Judicial de Sonora) para uno o
varios expedientes y avisa cuando se publica un acuerdo nuevo.

    https://adison.stjsonora.gob.mx/Publicacion/ListaAcuerdos/

No usa Selenium: la página consulta por AJAX el endpoint
/Controller/ActionController.php (Accion=Publicacion|ListaAcuerdosController|BuscarByAsunto)
y aquí se llama ese mismo endpoint directamente, lo que es más rápido y no se rompe
si cambia el diseño de la página.

Uso:
    python3 monitorear_expediente.py                    # revisa una vez y termina
    python3 monitorear_expediente.py --cada 30          # revisa cada 30 minutos (Ctrl+C para salir)
    python3 monitorear_expediente.py --resumen          # revisa y manda el resumen por WhatsApp
    python3 monitorear_expediente.py --probar-whatsapp  # manda un mensaje de prueba

Los expedientes a monitorear se configuran en .env (ADISON_EXPEDIENTES).
"""

import argparse
import json
import os
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

BASE_URL = "https://adison.stjsonora.gob.mx"
PAGINA_URL = f"{BASE_URL}/Publicacion/ListaAcuerdos/"
API_URL = f"{BASE_URL}/Controller/ActionController.php"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

# Rutas relativas al script (no al directorio actual) para que funcione desde cron.
# .env       -> datos de los expedientes (no se sube a git; plantilla en .env.example)
# .env.local -> secretos como la apikey de WhatsApp (no se sube a git); tiene prioridad
CARPETA = Path(__file__).resolve().parent
load_dotenv(CARPETA / ".env")
load_dotenv(CARPETA / ".env.local", override=True)

ARCHIVO_LOCK = CARPETA / ".monitor.lock"
DIAS_HISTORIAL = 8
MESES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


# ---------- Configuración de expedientes ----------

@dataclass
class Expediente:
    id_unidad: str
    id_grupo_ramo: str
    id_cat_ramo: str
    id_tipo_asunto: str
    asunto: str
    anio: str
    bis: str = "0"

    @property
    def nombre(self):
        return f"{self.asunto}/{self.anio}" + ("" if self.bis == "0" else f" (bis {self.bis})")

    @property
    def consulta(self):
        return {
            "IdUnidad": self.id_unidad,
            "IdCatGrupoRamo": self.id_grupo_ramo,
            "IdCatTipoAsunto": self.id_tipo_asunto,
            "Asunto": self.asunto,
            "Anio": self.anio,
            "Bis": self.bis,
        }

    @property
    def _sufijo(self):
        return f"{self.id_unidad}_{self.asunto}_{self.anio}_{self.bis}.json"

    @property
    def archivo_estado(self):  # acuerdos ya vistos
        return CARPETA / f"estado_{self._sufijo}"

    @property
    def archivo_historial(self):  # resultado de cada revisión, para el resumen
        return CARPETA / f"historial_{self._sufijo}"

    @property
    def link(self):
        return (
            f"{PAGINA_URL}?IdUnidad={self.id_unidad}&IdCatTipoAsunto={self.id_tipo_asunto}"
            f"&Asunto={self.asunto}&Anio={self.anio}&Bis={self.bis}&IdCatRamo={self.id_cat_ramo}"
        )


def cargar_expedientes():
    """Lee los expedientes de .env.

    ADISON_EXPEDIENTES es una lista separada por comas de asunto/año[/bis],
    p.ej. "123/2025, 45/2024". Todos comparten juzgado, ramo y tipo de asunto.
    Por compatibilidad, si no existe se usan ADISON_ASUNTO / ADISON_ANIO / ADISON_BIS.
    """
    comunes = {
        "id_unidad": "ADISON_ID_UNIDAD",
        "id_grupo_ramo": "ADISON_ID_GRUPO_RAMO",
        "id_cat_ramo": "ADISON_ID_CAT_RAMO",
        "id_tipo_asunto": "ADISON_ID_TIPO_ASUNTO",
    }
    faltantes = [v for v in comunes.values() if not os.getenv(v)]
    lista = (os.getenv("ADISON_EXPEDIENTES") or "").strip()
    if not lista:
        if os.getenv("ADISON_ASUNTO") and os.getenv("ADISON_ANIO"):
            lista = f"{os.getenv('ADISON_ASUNTO')}/{os.getenv('ADISON_ANIO')}/{os.getenv('ADISON_BIS') or '0'}"
        else:
            faltantes.append("ADISON_EXPEDIENTES")
    if faltantes:
        sys.exit(f"Faltan variables en {CARPETA / '.env'}: {', '.join(faltantes)} "
                 "(copia .env.example a .env y llénalo)")

    base = {campo: os.getenv(var).strip() for campo, var in comunes.items()}
    expedientes = []
    for item in lista.split(","):
        partes = [p.strip() for p in item.strip().split("/")]
        if not item.strip():
            continue
        if len(partes) not in (2, 3) or not all(p.isdigit() for p in partes):
            sys.exit(f"Expediente mal escrito en ADISON_EXPEDIENTES: {item.strip()!r} (usa asunto/año, p.ej. 123/2025)")
        asunto, anio, *bis = partes
        expedientes.append(Expediente(**base, asunto=asunto, anio=anio, bis=bis[0] if bis else "0"))
    return expedientes


EXPEDIENTES = cargar_expedientes()


# ---------- Consulta al sitio ----------

def consultar_acuerdos(exp):
    """Devuelve la lista de acuerdos publicados para el expediente (lista de dicts)."""
    with requests.Session() as s:
        s.headers.update(HEADERS)
        s.get(PAGINA_URL, timeout=30)  # obtiene la cookie de sesión, igual que el navegador
        # El sitio manda los datos como multipart/form-data (FormData de JS).
        campos = {"Accion": (None, "Publicacion|ListaAcuerdosController|BuscarByAsunto")}
        campos.update({k: (None, v) for k, v in exp.consulta.items()})
        resp = s.post(API_URL, files=campos, timeout=30)
    resp.raise_for_status()
    datos = resp.json()
    if str(datos.get("Estatus")) != "1":
        raise RuntimeError(f"El sitio respondió con error: {datos.get('Mensaje') or datos}")
    return datos.get("Resultado") or []


def clave(acuerdo):
    return str(acuerdo.get("IdDetalle") or acuerdo.get("Id"))


def limpio(texto):
    return " ".join((texto or "").split())


def resumen(acuerdo):
    return f"{acuerdo.get('Fecha')}  [{limpio(acuerdo.get('Secretaria'))}]  {limpio(acuerdo.get('Sintesis'))}"


def fecha_corta(iso):
    """'2025-07-09' -> '09-Jul-2025' (mismo formato que muestra la página)."""
    try:
        f = datetime.strptime(iso, "%Y-%m-%d")
    except (TypeError, ValueError):
        return str(iso)
    return f"{f.day:02d}-{MESES[f.month - 1]}-{f.year}"


def ahora_txt():
    return f"{datetime.now():%Y-%m-%d %H:%M}"


def imprimir_tabla(acuerdos):
    """Imprime los acuerdos en 4 columnas: Fecha Publicación, Secretaría, Partes, Síntesis."""
    columnas = [("Fecha Publicación", 17), ("Secretaría", 24), ("Partes", 24), ("Síntesis", 60)]
    separador = "+" + "+".join("-" * (ancho + 2) for _, ancho in columnas) + "+"

    def fila(celdas):
        envueltas = [textwrap.wrap(texto, ancho) or [""] for texto, (_, ancho) in zip(celdas, columnas)]
        for i in range(max(len(e) for e in envueltas)):
            print("| " + " | ".join(
                (e[i] if i < len(e) else "").ljust(ancho) for e, (_, ancho) in zip(envueltas, columnas)
            ) + " |")

    print(separador)
    fila([nombre for nombre, _ in columnas])
    print(separador.replace("-", "="))
    for a in acuerdos:
        fila([fecha_corta(a.get("Fecha")), limpio(a.get("Secretaria")),
              limpio(a.get("Partes")), limpio(a.get("Sintesis"))])
        print(separador)


# ---------- Estado (acuerdos ya vistos) ----------

def cargar_estado(exp):
    if not exp.archivo_estado.exists():
        return None
    return json.loads(exp.archivo_estado.read_text(encoding="utf-8"))


def guardar_estado(exp, acuerdos):
    estado = {
        "actualizado": datetime.now().isoformat(timespec="seconds"),
        "acuerdos": {clave(a): a for a in acuerdos},
    }
    exp.archivo_estado.write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------- Avisos ----------

def notificar(titulo, mensaje):
    """Notificación nativa de macOS (no hace nada en otros sistemas)."""
    if sys.platform != "darwin":
        return

    def cadena_applescript(texto):
        return '"' + texto.replace("\\", "\\\\").replace('"', '\\"') + '"'

    script = (f"display notification {cadena_applescript(mensaje)} "
              f"with title {cadena_applescript(titulo)} sound name \"Glass\"")
    subprocess.run(["osascript", "-e", script], check=False)


def normalizar_telefono(numero):
    """Deja solo dígitos y antepone '+' (CallMeBot espera formato internacional)."""
    digitos = "".join(c for c in (numero or "") if c.isdigit())
    return f"+{digitos}" if digitos else ""


WHATSAPP_TELEFONO = normalizar_telefono(os.getenv("WHATSAPP_TELEFONO"))
WHATSAPP_APIKEY = (os.getenv("WHATSAPP_APIKEY") or "").strip()


def whatsapp_configurado():
    return bool(WHATSAPP_TELEFONO and WHATSAPP_APIKEY)


def enviar_whatsapp(texto):
    """Envía `texto` a tu propio WhatsApp vía CallMeBot (https://www.callmebot.com).

    Requiere WHATSAPP_TELEFONO y WHATSAPP_APIKEY en .env.local. Lanza excepción si falla.
    """
    resp = requests.get(
        "https://api.callmebot.com/whatsapp.php",
        params={"phone": WHATSAPP_TELEFONO, "text": texto, "apikey": WHATSAPP_APIKEY},
        headers=HEADERS,
        timeout=60,
    )
    # CallMeBot responde 200 incluso en algunos errores; el detalle viene en el cuerpo.
    cuerpo = resp.text.lower()
    if resp.status_code != 200 or "error" in cuerpo or "invalid" in cuerpo:
        raise RuntimeError(f"CallMeBot respondió {resp.status_code}: {resp.text.strip()[:300]}")


def mensaje_whatsapp(exp, nuevos, modificados):
    lineas = [f"📋 *Exp. {exp.nombre}* - cambios en la Lista de Acuerdos"]
    for etiqueta, grupo in (("🆕 Nuevo", nuevos), ("✏️ Modificado", modificados)):
        for a in grupo:
            lineas.append(f"\n{etiqueta} · {fecha_corta(a.get('Fecha'))}\n{limpio(a.get('Sintesis'))[:300]}")
    lineas.append(f"\nVer: {exp.link}")
    return "\n".join(lineas)


# ---------- Historial de revisiones (para el resumen por WhatsApp) ----------

def cargar_historial(exp):
    if not exp.archivo_historial.exists():
        return {"ultimo_resumen": None, "revisiones": []}
    return json.loads(exp.archivo_historial.read_text(encoding="utf-8"))


def guardar_historial(exp, historial):
    exp.archivo_historial.write_text(json.dumps(historial, ensure_ascii=False, indent=2), encoding="utf-8")


def registrar_revision(exp, ok, total=None, cambios=None, error=None):
    """Anota el resultado de una revisión. Nunca lanza excepción (no debe tumbar el monitor)."""
    try:
        historial = cargar_historial(exp)
        limite = (datetime.now() - timedelta(days=DIAS_HISTORIAL)).isoformat(timespec="seconds")
        historial["revisiones"] = [r for r in historial["revisiones"] if r["hora"] >= limite]
        historial["revisiones"].append({
            "hora": datetime.now().isoformat(timespec="seconds"),
            "ok": ok,
            "total": total,
            "cambios": cambios or [],
            "error": error,
        })
        guardar_historial(exp, historial)
    except Exception as exc:
        print(f"  (no se pudo escribir el historial de {exp.nombre}: {exc})", file=sys.stderr)


def describir_cambios(nuevos, modificados):
    return (
        [{"tipo": "Nuevo", "fecha": a.get("Fecha"), "sintesis": limpio(a.get("Sintesis"))} for a in nuevos]
        + [{"tipo": "Modificado", "fecha": a.get("Fecha"), "sintesis": limpio(a.get("Sintesis"))}
           for a in modificados]
    )


def hora_legible(iso, referencia=None):
    """'2026-11-18T13:00:00' -> '13:00' si es el mismo día que `referencia`, si no '18-Nov 13:00'."""
    dt = datetime.fromisoformat(iso)
    referencia = referencia or datetime.now()
    if dt.date() == referencia.date():
        return dt.strftime("%H:%M")
    return f"{dt.day:02d}-{MESES[dt.month - 1]} {dt:%H:%M}"


def seccion_resumen(exp, historial, ahora):
    """Líneas del resumen para un expediente."""
    revisiones = historial["revisiones"]
    desde = historial.get("ultimo_resumen") or (revisiones[0]["hora"] if revisiones else None)
    if historial.get("ultimo_resumen") is None:
        periodo = revisiones  # primer resumen: incluye todo lo registrado
        desde_txt = f"que empezó el registro ({hora_legible(desde, ahora)})" if desde else "el inicio"
    else:
        periodo = [r for r in revisiones if r["hora"] > desde]
        desde_txt = hora_legible(desde, ahora)

    correctas = [r for r in periodo if r["ok"]]
    errores = [r for r in periodo if not r["ok"]]
    cambios = [(r["hora"], c) for r in correctas for c in r["cambios"]]

    lineas = [f"*Exp. {exp.nombre}*"]
    if not periodo:
        lineas.append(f"⚠️ No hubo revisiones desde {desde_txt}. Revisa la Raspberry Pi / cron.")
    elif cambios:
        lineas.append(f"🆕 Hubo {len(cambios)} cambio(s) desde {desde_txt}:")
        for hora, c in cambios:
            lineas.append(f"• {hora_legible(hora, ahora)} · {c['tipo']} ({fecha_corta(c['fecha'])}): "
                          f"{c['sintesis'][:200]}")
    else:
        lineas.append(f"✅ Sin cambios desde {desde_txt}.")

    if periodo:
        detalle = f"Revisiones: {len(correctas)} correcta{'s' if len(correctas) != 1 else ''}"
        if errores:
            ultimo = errores[-1]
            detalle += (f", ⚠️ {len(errores)} con error (el último a las {hora_legible(ultimo['hora'], ahora)}: "
                        f"{(ultimo['error'] or '')[:120]})")
        lineas.append(detalle + ".")
    ultima_ok = next((r for r in reversed(revisiones) if r["ok"]), None)
    if ultima_ok:
        lineas.append(f"Última revisión correcta: {hora_legible(ultima_ok['hora'], ahora)} · "
                      f"{ultima_ok['total']} acuerdos en total.")
    if cambios:
        lineas.append(f"Ver: {exp.link}")
    return lineas


def armar_resumen(historiales, ahora=None):
    """`historiales` es una lista de (expediente, historial). Devuelve un solo mensaje."""
    ahora = ahora or datetime.now()
    lineas = [f"📋 *Lista de Acuerdos* · Resumen {ahora:%H:%M}"]
    for exp, historial in historiales:
        lineas.append("")
        lineas.extend(seccion_resumen(exp, historial, ahora))
    return "\n".join(lineas)


def enviar_resumen():
    """Revisa una vez más, arma el resumen desde el último enviado y lo manda por WhatsApp."""
    revisar_todos(mostrar_lista=False)

    historiales = [(exp, cargar_historial(exp)) for exp in EXPEDIENTES]
    texto = armar_resumen(historiales)
    print(f"[{ahora_txt()}] Resumen:\n{texto}")

    if not whatsapp_configurado():
        print("  (WhatsApp no configurado en .env.local; el resumen solo se imprimió)")
        return
    try:
        enviar_whatsapp(texto)
    except Exception as exc:
        # No se marca como enviado: el siguiente resumen cubrirá también este periodo.
        print(f"  ERROR al enviar el resumen por WhatsApp: {exc}", file=sys.stderr)
        sys.exit(1)
    marca = datetime.now().isoformat(timespec="seconds")
    for exp, historial in historiales:
        historial["ultimo_resumen"] = marca
        guardar_historial(exp, historial)
    print("  Resumen enviado por WhatsApp.")


# ---------- Revisión ----------

def revisar(exp, mostrar_lista=True):
    """Consulta el sitio para un expediente, compara contra la revisión anterior y avisa de cambios.

    Si `mostrar_lista` es True imprime siempre la tabla completa de acuerdos;
    si es False solo la imprime cuando hay cambios.
    Devuelve True si hubo cambios (acuerdos nuevos o modificados).
    """
    acuerdos = consultar_acuerdos(exp)
    estado = cargar_estado(exp)

    if estado is None:
        guardar_estado(exp, acuerdos)
        registrar_revision(exp, ok=True, total=len(acuerdos))
        print(f"[{ahora_txt()}] Primera revisión del Exp. {exp.nombre}: {len(acuerdos)} acuerdos guardados como base.")
        if mostrar_lista:
            imprimir_tabla(acuerdos)
        return False

    previos = estado.get("acuerdos", {})
    nuevos = [a for a in acuerdos if clave(a) not in previos]
    modificados = [
        a for a in acuerdos
        if clave(a) in previos
        and (a.get("Sintesis"), a.get("Fecha")) != (previos[clave(a)].get("Sintesis"), previos[clave(a)].get("Fecha"))
    ]

    if not nuevos and not modificados:
        registrar_revision(exp, ok=True, total=len(acuerdos))
        print(f"[{ahora_txt()}] Sin cambios en Exp. {exp.nombre} ({len(acuerdos)} acuerdos).")
        if mostrar_lista:
            imprimir_tabla(acuerdos)
        return False

    print(f"[{ahora_txt()}] ¡Cambios en Exp. {exp.nombre}!")
    imprimir_tabla(acuerdos)
    for a in nuevos:
        print(f"  NUEVO:      {resumen(a)}")
    for a in modificados:
        print(f"  MODIFICADO: {resumen(a)}")
    print(f"  Ver: {exp.link}")

    cambios = nuevos + modificados
    mensaje = limpio(cambios[0].get("Sintesis"))[:120]
    if len(cambios) > 1:
        mensaje = f"{len(cambios)} cambios. Último: {limpio(cambios[-1].get('Sintesis'))[:100]}"
    notificar(f"Nuevo acuerdo · Exp. {exp.nombre}", mensaje)

    if whatsapp_configurado():
        try:
            enviar_whatsapp(mensaje_whatsapp(exp, nuevos, modificados))
            print("  Aviso enviado por WhatsApp.")
        except Exception as exc:
            # No guardamos el estado: así la próxima revisión vuelve a detectar
            # el cambio y reintenta el aviso, en vez de perderlo.
            print(f"  ERROR al enviar WhatsApp (se reintenta en la próxima revisión): {exc}", file=sys.stderr)
            registrar_revision(exp, ok=False, error=f"No se pudo enviar el aviso por WhatsApp: {exc}"[:300])
            return True

    guardar_estado(exp, acuerdos)
    registrar_revision(exp, ok=True, total=len(acuerdos), cambios=describir_cambios(nuevos, modificados))
    return True


def revisar_todos(mostrar_lista=True):
    """Revisa cada expediente; un error en uno no impide revisar los demás.

    Devuelve True si todos se revisaron sin error.
    """
    todo_ok = True
    for exp in EXPEDIENTES:
        try:
            revisar(exp, mostrar_lista=mostrar_lista)
        except Exception as exc:
            todo_ok = False
            print(f"[{ahora_txt()}] ERROR al revisar Exp. {exp.nombre}: {exc}", file=sys.stderr)
            registrar_revision(exp, ok=False, error=str(exc)[:300])
    return todo_ok


def main():
    parser = argparse.ArgumentParser(description="Monitorea expedientes en la Lista de Acuerdos de ADISON.")
    parser.add_argument("--cada", type=float, metavar="MINUTOS",
                        help="repetir la revisión cada N minutos (si se omite, revisa una sola vez)")
    parser.add_argument("--probar-whatsapp", action="store_true",
                        help="envía un mensaje de prueba por WhatsApp y termina")
    parser.add_argument("--resumen", action="store_true",
                        help="revisa y envía por WhatsApp el resumen desde el último resumen enviado")
    args = parser.parse_args()

    # Evita que dos ejecuciones (p.ej. la revisión de cron y el resumen a la misma
    # hora) lean/escriban los archivos de estado al mismo tiempo y avisen doble.
    import fcntl
    lock = open(ARCHIVO_LOCK, "w")
    fcntl.flock(lock, fcntl.LOCK_EX)

    if args.resumen:
        enviar_resumen()
        return

    if args.probar_whatsapp:
        if not whatsapp_configurado():
            sys.exit("Falta WHATSAPP_TELEFONO y/o WHATSAPP_APIKEY en .env.local (ver .env.local.example).")
        nombres = ", ".join(f"Exp. {e.nombre}" for e in EXPEDIENTES)
        try:
            enviar_whatsapp(f"✅ Prueba del monitor de la Lista de Acuerdos ({nombres}). "
                            "Si lees esto, los avisos por WhatsApp funcionan.")
        except Exception as exc:
            sys.exit(f"ERROR al enviar WhatsApp: {exc}")
        print("Mensaje de prueba enviado por WhatsApp.")
        return

    if not args.cada:
        # En terminal se muestra siempre la tabla; desde cron (salida a un archivo)
        # solo cuando hay cambios, para que el log quede con una línea por expediente.
        if not revisar_todos(mostrar_lista=sys.stdout.isatty()):
            sys.exit(1)
        return

    nombres = ", ".join(e.nombre for e in EXPEDIENTES)
    print(f"Monitoreando Exp. {nombres} cada {args.cada:g} min. Ctrl+C para salir.")
    primera_vuelta = True
    while True:
        # En modo continuo la tabla se muestra al arrancar y luego solo cuando hay cambios.
        revisar_todos(mostrar_lista=primera_vuelta)
        primera_vuelta = False
        try:
            time.sleep(args.cada * 60)
        except KeyboardInterrupt:
            print("\nMonitoreo detenido.")
            return


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nMonitoreo detenido.")
