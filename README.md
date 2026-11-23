# Monitoreo de Lista de Acuerdos (ADISON Sonora)

Revisa la [Lista de Acuerdos de ADISON](https://adison.stjsonora.gob.mx/Publicacion/ListaAcuerdos/)
del Poder Judicial del Estado de Sonora para uno o varios expedientes, muestra sus
acuerdos y avisa cuando se publica uno nuevo. Los expedientes a monitorear se configuran en
`.env` (ver [Configuración](#configuración)).

## Cómo funciona

La página de ADISON no trae los acuerdos en su HTML: al dar clic en **Buscar**
los pide por AJAX a `/Controller/ActionController.php` (acción
`Publicacion|ListaAcuerdosController|BuscarByAsunto`). El script hace esa misma
petición directamente, así que:

- no necesita navegador ni Selenium (corre bien en una Raspberry Pi),
- tarda un par de segundos,
- no se rompe si cambia el diseño de la página.

En cada revisión:

1. Consulta los acuerdos del expediente.
2. Los compara contra los de la revisión anterior, guardados en
   `estado_<unidad>_<asunto>_<año>_<bis>.json`.
3. Si hay acuerdos **nuevos** o **modificados**, los imprime con el link al
   expediente y avisa:
   - por **WhatsApp**, si está configurado (ver [Avisos por WhatsApp](#avisos-por-whatsapp)),
   - con una notificación del sistema si corre en macOS.

La primera vez solo guarda los acuerdos actuales como punto de partida, sin
avisar. Si borras el archivo de estado, vuelve a tomar el punto de partida.

## Requisitos

- Python 3.8 o superior
- Conexión a internet

## Instalación

```bash
git clone <url-del-repo> monitoreo-lista-acuerdos
cd monitoreo-lista-acuerdos
python3 -m venv venv
venv/bin/pip install -r requirements.txt
cp .env.example .env     # y edita ADISON_EXPEDIENTES con tus expedientes
```

## Uso

```bash
venv/bin/python3 monitorear_expediente.py             # revisa una vez y termina
venv/bin/python3 monitorear_expediente.py --cada 30   # revisa cada 30 min (Ctrl+C para salir)
```

Ejemplo de salida:

```
[AAAA-MM-DD HH:MM] Sin cambios en Exp. <asunto>/<año> (<n> acuerdos).
+-------------------+--------------------------+--------------------------+------------------------------------------+
| Fecha Publicación | Secretaría               | Partes                   | Síntesis                                 |
+===================+==========================+==========================+==========================================+
| DD-Mmm-AAAA       | <secretaría>             | <partes>                 | <síntesis del acuerdo>                   |
+-------------------+--------------------------+--------------------------+------------------------------------------+
| ...               | ...                      | ...                      | ...                                      |
+-------------------+--------------------------+--------------------------+------------------------------------------+
```

Cuando hay cambios, además de la tabla:

```
[AAAA-MM-DD HH:MM] ¡Cambios en Exp. <asunto>/<año>!
  NUEVO:      AAAA-MM-DD  [<secretaría>]  <síntesis del acuerdo>
  Ver: https://adison.stjsonora.gob.mx/Publicacion/ListaAcuerdos/?IdUnidad=...
```

- Una sola revisión siempre imprime la tabla completa.
- Con `--cada`, la tabla se imprime al arrancar y después solo cuando hay cambios.

## Correrlo automáticamente (Raspberry Pi / Linux / macOS)

Con `cron`: ejecuta `crontab -e` y agrega una línea. Por ejemplo, cada 30
minutos de 7:00 a 21:59, de lunes a viernes:

```
*/30 7-21 * * 1-5 cd /home/pi/monitoreo-lista-acuerdos && venv/bin/python3 monitorear_expediente.py >> monitoreo.log 2>&1
```

### Revisar que esté sano

Desde cron cada revisión deja **una línea con fecha y hora** en `monitoreo.log`
(la tabla completa solo se escribe cuando hay cambios):

```
[2026-11-18 18:30] Sin cambios en Exp. <asunto>/<año> (<n> acuerdos).
[2026-11-18 19:00] ERROR al revisar: <detalle del error>
[2026-11-18 19:30] ¡Cambios en Exp. <asunto>/<año>!
```

```bash
tail -5 monitoreo.log            # últimas revisiones (debe haber una cada 30 min)
grep ERROR monitoreo.log | tail  # últimos errores
grep "Cambios" monitoreo.log     # cuándo hubo acuerdos nuevos
```

Un error aislado (sin internet, sitio caído) no es problema: la siguiente
revisión lo intenta de nuevo y no se pierde ningún acuerdo.

> El script carga `.env` desde su propia carpeta, así que funciona aunque cron
> lo ejecute desde otro directorio.

## Configuración

### `.env` — expedientes a monitorear (no se sube a git)

Plantilla en `.env.example`.

| Variable | Qué es | Ejemplo |
|---|---|---|
| `ADISON_ID_UNIDAD` | `value` del Órgano Jurisdiccional | `157` (Juzgado 3º Familiar Hermosillo) |
| `ADISON_ID_GRUPO_RAMO` | `data-value` del Ramo | `1` (FAMILIAR) |
| `ADISON_ID_CAT_RAMO` | `value` del Ramo (solo para armar el link) | `2` (FAMILIAR) |
| `ADISON_ID_TIPO_ASUNTO` | `value` del Tipo Asunto | `1` (EXPEDIENTE) |
| `ADISON_EXPEDIENTES` | Expedientes `asunto/año`, separados por coma | `123/2025, 45/2024` |

Para **agregar o quitar un expediente** del mismo juzgado, edita
`ADISON_EXPEDIENTES`. Si alguno lleva BIS, agrega el `value` de Bis como tercer
número: `123/2025/1` (`1` = BIS, `3` = TER…). Al agregar uno, la primera revisión
guarda sus acuerdos actuales como base sin avisar.

Los IDs salen de los
`<select>` del formulario: en la página, clic derecho sobre el campo >
**Inspeccionar** y busca el `<option>` correspondiente.

### `.env.local` — secretos (no se sube a git)

Tu número y la apikey de WhatsApp van en `.env.local` (plantilla en
`.env.local.example`). Si existe, sus valores tienen prioridad sobre los de `.env`.

## Avisos por WhatsApp

Se usa [CallMeBot](https://www.callmebot.com/blog/free-api-whatsapp-messages/),
un servicio gratuito (no oficial) para mandarte mensajes a tu propio WhatsApp.

1. Sigue las instrucciones de la página de CallMeBot: agrega su número a tus
   contactos y mándale por WhatsApp el mensaje de activación que indica. Te
   responde con tu **apikey**.
2. Crea `.env.local` y llénalo:

   ```bash
   cp .env.local.example .env.local
   nano .env.local
   ```

   ```
   WHATSAPP_TELEFONO=+52XXXXXXXXXX
   WHATSAPP_APIKEY=1234567
   ```

3. Prueba que llegue:

   ```bash
   venv/bin/python3 monitorear_expediente.py --probar-whatsapp
   ```

Cuando hay un acuerdo nuevo llega un mensaje con la fecha, la síntesis y el link
al expediente.

### Resumen a mediodía y al final del día

`--resumen` hace una revisión y manda por WhatsApp lo que pasó desde el resumen
anterior: si hubo cambios (y a qué hora se detectaron), cuántas revisiones
funcionaron y si hubo errores. Agrega estas líneas a `crontab -e`:

```
0 12 * * 1-5 cd /ruta/al/proyecto && /ruta/al/venv/bin/python3 monitorear_expediente.py --resumen >> monitoreo.log 2>&1
0 22 * * 1-5 cd /ruta/al/proyecto && /ruta/al/venv/bin/python3 monitorear_expediente.py --resumen >> monitoreo.log 2>&1
```

Ejemplos:

Llega un solo mensaje con una sección por expediente:

```
📋 Lista de Acuerdos · Resumen 22:00

Exp. <asunto>/<año>
🆕 Hubo 1 cambio(s) desde 12:00:
• 14:00 · Nuevo (DD-Mmm-AAAA): <síntesis del acuerdo>
Revisiones: 19 correctas, ⚠️ 1 con error (el último a las 13:30: Read timed out).
Última revisión correcta: 22:00 · <n> acuerdos en total.
Ver: https://adison.stjsonora.gob.mx/...

Exp. <asunto>/<año>
✅ Sin cambios desde 12:00.
Revisiones: 20 correctas.
Última revisión correcta: 22:00 · <n> acuerdos en total.
```

Si un resumen esperado **no llega**, la Raspberry Pi está apagada, sin internet
o cron no está corriendo. Si llega con "⚠️ No hubo revisiones", cron no está
ejecutando las revisiones cada 30 minutos.

El resultado de cada revisión se guarda en `historial_*.json` (últimos 8 días,
no se sube a git). Un candado (`.monitor.lock`) evita que la revisión y el
resumen corran al mismo tiempo. Si el envío falla (sin internet, CallMeBot caído), el cambio no
se marca como visto y se reintenta en la siguiente revisión, para no perder el
aviso.

## Archivos

| Archivo | Descripción |
|---|---|
| `monitorear_expediente.py` | Script principal |
| `.env` | Expedientes a monitorear (ignorado por git) |
| `.env.example` | Plantilla de `.env` |
| `.env.local` | Teléfono y apikey de WhatsApp (ignorado por git) |
| `.env.local.example` | Plantilla de `.env.local` |
| `estado_*.json` | Acuerdos ya vistos (se genera solo, ignorado por git) |
| `historial_*.json` | Resultado de cada revisión, para el resumen (ignorado por git) |
| `monitoreo.log` | Salida de cron (si lo configuras así, ignorado por git) |
| `requirements.txt` | Dependencias: `requests`, `python-dotenv` |
