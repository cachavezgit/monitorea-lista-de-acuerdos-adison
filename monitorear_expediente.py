"""
Monitorea la Lista de Acuerdos de ADISON (Poder Judicial de Sonora) para un
expediente y avisa cuando se publica un acuerdo nuevo.

    https://adison.stjsonora.gob.mx/Publicacion/ListaAcuerdos/

No usa Selenium: la página consulta por AJAX el endpoint
/Controller/ActionController.php (Accion=Publicacion|ListaAcuerdosController|BuscarByAsunto)
y aquí se llama ese mismo endpoint directamente, lo que es más rápido y no se rompe
si cambia el diseño de la página.

Uso:
    python3 monitorear_expediente.py              # revisa una vez y termina
    python3 monitorear_expediente.py --cada 30    # revisa cada 30 minutos (Ctrl+C para salir)

El expediente a monitorear se configura en .env (actualmente Exp. 649/2025,
Juzgado Tercero de Primera Instancia de lo Familiar de Hermosillo).
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

BASE_URL = "https://adison.stjsonora.gob.mx"
PAGINA_URL = f"{BASE_URL}/Publicacion/ListaAcuerdos/"
API_URL = f"{BASE_URL}/Controller/ActionController.php"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

# Rutas relativas al script (no al directorio actual) para que funcione desde cron.
# .env       -> datos del expediente (se sube a git)
# .env.local -> secretos como tokens (no se sube a git); si existe, tiene prioridad
CARPETA = Path(__file__).resolve().parent
load_dotenv(CARPETA / ".env")
load_dotenv(CARPETA / ".env.local", override=True)

# IDs internos del sitio (salen de los <select> del formulario); ver .env.
VARIABLES = {
    "IdUnidad": "ADISON_ID_UNIDAD",
    "IdCatGrupoRamo": "ADISON_ID_GRUPO_RAMO",
    "IdCatTipoAsunto": "ADISON_ID_TIPO_ASUNTO",
    "Asunto": "ADISON_ASUNTO",
    "Anio": "ADISON_ANIO",
    "Bis": "ADISON_BIS",
}
faltantes = [v for v in [*VARIABLES.values(), "ADISON_ID_CAT_RAMO"] if not os.getenv(v)]
if faltantes:
    sys.exit(f"Faltan variables en {CARPETA / '.env'}: {', '.join(faltantes)}")

CONSULTA = {campo: os.getenv(var).strip() for campo, var in VARIABLES.items()}
ID_CAT_RAMO = os.getenv("ADISON_ID_CAT_RAMO").strip()  # solo para armar el link

EXPEDIENTE = f"{CONSULTA['Asunto']}/{CONSULTA['Anio']}"
_SUFIJO = f"{CONSULTA['IdUnidad']}_{CONSULTA['Asunto']}_{CONSULTA['Anio']}_{CONSULTA['Bis']}.json"
ARCHIVO_ESTADO = CARPETA / f"estado_{_SUFIJO}"        # acuerdos ya vistos
ARCHIVO_HISTORIAL = CARPETA / f"historial_{_SUFIJO}"  # resultado de cada revisión, para el resumen
ARCHIVO_LOCK = CARPETA / ".monitor.lock"
DIAS_HISTORIAL = 8
LINK_EXPEDIENTE = (
    f"{PAGINA_URL}?IdUnidad={CONSULTA['IdUnidad']}&IdCatTipoAsunto={CONSULTA['IdCatTipoAsunto']}"
    f"&Asunto={CONSULTA['Asunto']}&Anio={CONSULTA['Anio']}&Bis={CONSULTA['Bis']}&IdCatRamo={ID_CAT_RAMO}"
)


def consultar_acuerdos():
    """Devuelve la lista de acuerdos publicados para el expediente (lista de dicts)."""
    with requests.Session() as s:
        s.headers.update(HEADERS)
        s.get(PAGINA_URL, timeout=30)  # obtiene la cookie de sesión, igual que el navegador
        # El sitio manda los datos como multipart/form-data (FormData de JS).
        campos = {"Accion": (None, "Publicacion|ListaAcuerdosController|BuscarByAsunto")}
        campos.update({k: (None, v) for k, v in CONSULTA.items()})
        resp = s.post(API_URL, files=campos, timeout=30)
    resp.raise_for_status()
    datos = resp.json()
    if str(datos.get("Estatus")) != "1":
        raise RuntimeError(f"El sitio respondió con error: {datos.get('Mensaje') or datos}")
    return datos.get("Resultado") or []


def clave(acuerdo):
    return str(acuerdo.get("IdDetalle") or acuerdo.get("Id"))


def resumen(acuerdo):
    sec = (acuerdo.get("Secretaria") or "").strip()
    return f"{acuerdo.get('Fecha')}  [{sec}]  {(acuerdo.get('Sintesis') or '').strip()}"


MESES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


def fecha_corta(iso):
    """'2025-07-09' -> '09-Jul-2025' (mismo formato que muestra la página)."""
    try:
        f = datetime.strptime(iso, "%Y-%m-%d")
    except (TypeError, ValueError):
        return str(iso)
    return f"{f.day:02d}-{MESES[f.month - 1]}-{f.year}"


def imprimir_tabla(acuerdos):
    """Imprime los acuerdos en 4 columnas: Fecha Publicación, Secretaría, Partes, Síntesis."""
    import textwrap

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
        fila([
            fecha_corta(a.get("Fecha")),
            " ".join((a.get("Secretaria") or "").split()),
            " ".join((a.get("Partes") or "").split()),
            " ".join((a.get("Sintesis") or "").split()),
        ])
        print(separador)


def cargar_estado():
    if not ARCHIVO_ESTADO.exists():
        return None
    return json.loads(ARCHIVO_ESTADO.read_text(encoding="utf-8"))


def guardar_estado(acuerdos):
    estado = {
        "actualizado": datetime.now().isoformat(timespec="seconds"),
        "acuerdos": {clave(a): a for a in acuerdos},
    }
    ARCHIVO_ESTADO.write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")


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


def mensaje_whatsapp(nuevos, modificados):
    lineas = [f"📋 *Exp. {EXPEDIENTE}* - cambios en la Lista de Acuerdos"]
    for etiqueta, grupo in (("🆕 Nuevo", nuevos), ("✏️ Modificado", modificados)):
        for a in grupo:
            sintesis = " ".join((a.get("Sintesis") or "").split())[:300]
            lineas.append(f"\n{etiqueta} · {fecha_corta(a.get('Fecha'))}\n{sintesis}")
    lineas.append(f"\nVer: {LINK_EXPEDIENTE}")
    return "\n".join(lineas)


# ---------- Historial de revisiones (para el resumen por WhatsApp) ----------

def cargar_historial():
    if not ARCHIVO_HISTORIAL.exists():
        return {"ultimo_resumen": None, "revisiones": []}
    return json.loads(ARCHIVO_HISTORIAL.read_text(encoding="utf-8"))


def guardar_historial(historial):
    ARCHIVO_HISTORIAL.write_text(json.dumps(historial, ensure_ascii=False, indent=2), encoding="utf-8")


def registrar_revision(ok, total=None, cambios=None, error=None):
    """Anota el resultado de una revisión. Nunca lanza excepción (no debe tumbar el monitor)."""
    try:
        historial = cargar_historial()
        limite = (datetime.now() - timedelta(days=DIAS_HISTORIAL)).isoformat(timespec="seconds")
        historial["revisiones"] = [r for r in historial["revisiones"] if r["hora"] >= limite]
        historial["revisiones"].append({
            "hora": datetime.now().isoformat(timespec="seconds"),
            "ok": ok,
            "total": total,
            "cambios": cambios or [],
            "error": error,
        })
        guardar_historial(historial)
    except Exception as exc:
        print(f"  (no se pudo escribir el historial: {exc})", file=sys.stderr)


def describir_cambios(nuevos, modificados):
    return (
        [{"tipo": "Nuevo", "fecha": a.get("Fecha"), "sintesis": " ".join((a.get("Sintesis") or "").split())}
         for a in nuevos]
        + [{"tipo": "Modificado", "fecha": a.get("Fecha"), "sintesis": " ".join((a.get("Sintesis") or "").split())}
           for a in modificados]
    )


def hora_legible(iso, referencia=None):
    """'2026-11-18T13:00:00' -> '13:00' si es el mismo día que `referencia`, si no '18-Nov 13:00'."""
    dt = datetime.fromisoformat(iso)
    referencia = referencia or datetime.now()
    if dt.date() == referencia.date():
        return dt.strftime("%H:%M")
    return f"{dt.day:02d}-{MESES[dt.month - 1]} {dt:%H:%M}"


def armar_resumen(historial, ahora=None):
    ahora = ahora or datetime.now()
    revisiones = historial["revisiones"]
    desde = historial.get("ultimo_resumen") or (revisiones[0]["hora"] if revisiones else None)
    periodo = [r for r in revisiones if desde is None or r["hora"] > desde]
    if historial.get("ultimo_resumen") is None and revisiones:
        periodo = revisiones  # primer resumen: incluye todo lo registrado

    correctas = [r for r in periodo if r["ok"]]
    errores = [r for r in periodo if not r["ok"]]
    cambios = [(r["hora"], c) for r in correctas for c in r["cambios"]]
    if historial.get("ultimo_resumen"):
        desde_txt = hora_legible(desde, ahora)
    elif desde:
        desde_txt = f"que empezó el registro ({hora_legible(desde, ahora)})"
    else:
        desde_txt = "el inicio"

    lineas = [f"📋 *Exp. {EXPEDIENTE}* · Resumen {ahora:%H:%M}"]
    if not periodo:
        lineas.append(f"⚠️ No hubo revisiones desde {desde_txt}. Revisa la Raspberry Pi / cron.")
    elif cambios:
        lineas.append(f"🆕 Hubo {len(cambios)} cambio(s) desde {desde_txt}:")
        for hora, c in cambios:
            lineas.append(f"• {hora_legible(hora, ahora)} · {c['tipo']} ({fecha_corta(c['fecha'])}): {c['sintesis'][:200]}")
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
        lineas.append(f"Ver: {LINK_EXPEDIENTE}")
    return "\n".join(lineas)


def enviar_resumen():
    """Revisa una vez más, arma el resumen desde el último enviado y lo manda por WhatsApp."""
    try:
        revisar(mostrar_lista=False)
    except Exception as exc:
        print(f"[{datetime.now():%Y-%m-%d %H:%M}] ERROR al revisar: {exc}", file=sys.stderr)
        registrar_revision(ok=False, error=str(exc)[:300])

    historial = cargar_historial()
    texto = armar_resumen(historial)
    print(f"[{datetime.now():%Y-%m-%d %H:%M}] Resumen:\n{texto}")

    if not whatsapp_configurado():
        print("  (WhatsApp no configurado en .env.local; el resumen solo se imprimió)")
        return
    try:
        enviar_whatsapp(texto)
    except Exception as exc:
        # No se marca como enviado: el siguiente resumen cubrirá también este periodo.
        print(f"  ERROR al enviar el resumen por WhatsApp: {exc}", file=sys.stderr)
        sys.exit(1)
    historial["ultimo_resumen"] = datetime.now().isoformat(timespec="seconds")
    guardar_historial(historial)
    print("  Resumen enviado por WhatsApp.")


def revisar(mostrar_lista=True):
    """Consulta el sitio, compara contra la última revisión y reporta cambios.

    Si `mostrar_lista` es True imprime siempre la tabla completa de acuerdos;
    si es False solo la imprime cuando hay cambios.
    Devuelve True si hubo cambios (acuerdos nuevos o modificados).
    """
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M")
    acuerdos = consultar_acuerdos()
    estado = cargar_estado()

    if estado is None:
        guardar_estado(acuerdos)
        registrar_revision(ok=True, total=len(acuerdos))
        print(f"[{ahora}] Primera revisión del Exp. {EXPEDIENTE}: {len(acuerdos)} acuerdos guardados como base.")
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
        registrar_revision(ok=True, total=len(acuerdos))
        print(f"[{ahora}] Sin cambios en Exp. {EXPEDIENTE} ({len(acuerdos)} acuerdos).")
        if mostrar_lista:
            imprimir_tabla(acuerdos)
        return False

    print(f"[{ahora}] ¡Cambios en Exp. {EXPEDIENTE}!")
    imprimir_tabla(acuerdos)
    for a in nuevos:
        print(f"  NUEVO:      {resumen(a)}")
    for a in modificados:
        print(f"  MODIFICADO: {resumen(a)}")
    print(f"  Ver: {LINK_EXPEDIENTE}")

    cambios = nuevos + modificados
    mensaje = (cambios[0].get("Sintesis") or "").strip()[:120]
    if len(cambios) > 1:
        mensaje = f"{len(cambios)} cambios. Último: {(cambios[-1].get('Sintesis') or '').strip()[:100]}"
    notificar(f"Nuevo acuerdo · Exp. {EXPEDIENTE}", mensaje)

    if whatsapp_configurado():
        try:
            enviar_whatsapp(mensaje_whatsapp(nuevos, modificados))
            print("  Aviso enviado por WhatsApp.")
        except Exception as exc:
            # No guardamos el estado: así la próxima revisión vuelve a detectar
            # el cambio y reintenta el aviso, en vez de perderlo.
            print(f"  ERROR al enviar WhatsApp (se reintenta en la próxima revisión): {exc}", file=sys.stderr)
            registrar_revision(ok=False, error=f"No se pudo enviar el aviso por WhatsApp: {exc}"[:300])
            return True

    guardar_estado(acuerdos)
    registrar_revision(ok=True, total=len(acuerdos), cambios=describir_cambios(nuevos, modificados))
    return True


def main():
    parser = argparse.ArgumentParser(description="Monitorea un expediente en la Lista de Acuerdos de ADISON.")
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
        try:
            enviar_whatsapp(f"✅ Prueba del monitor de la Lista de Acuerdos (Exp. {EXPEDIENTE}). "
                            "Si lees esto, los avisos por WhatsApp funcionan.")
        except Exception as exc:
            sys.exit(f"ERROR al enviar WhatsApp: {exc}")
        print("Mensaje de prueba enviado por WhatsApp.")
        return

    if not args.cada:
        # En terminal se muestra siempre la tabla; desde cron (salida a un archivo)
        # solo cuando hay cambios, para que el log quede con una línea por revisión.
        try:
            revisar(mostrar_lista=sys.stdout.isatty())
        except Exception as exc:
            print(f"[{datetime.now():%Y-%m-%d %H:%M}] ERROR al revisar: {exc}", file=sys.stderr)
            registrar_revision(ok=False, error=str(exc)[:300])
            sys.exit(1)
        return

    print(f"Monitoreando Exp. {EXPEDIENTE} cada {args.cada:g} min. Ctrl+C para salir.")
    primera_vuelta = True
    while True:
        try:
            # En modo continuo la tabla se muestra al arrancar y luego solo cuando hay cambios.
            revisar(mostrar_lista=primera_vuelta)
            primera_vuelta = False
        except Exception as exc:  # un fallo de red no debe detener el monitoreo
            print(f"[{datetime.now():%Y-%m-%d %H:%M}] ERROR al revisar (se reintenta en la próxima vuelta): {exc}",
                  file=sys.stderr)
            registrar_revision(ok=False, error=str(exc)[:300])
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
