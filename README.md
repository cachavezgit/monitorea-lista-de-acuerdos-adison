# Monitoreo de Lista de Acuerdos (ADISON Sonora)

Revisa la [Lista de Acuerdos de ADISON](https://adison.stjsonora.gob.mx/Publicacion/ListaAcuerdos/)
del Poder Judicial del Estado de Sonora para un expediente, muestra sus acuerdos
y avisa cuando se publica uno nuevo.

Expediente configurado actualmente en `.env`:

> **Exp. 649/2025** — Juzgado Tercero de Primera Instancia de lo Familiar de Hermosillo
> (Ramo Familiar, Acuerdos por asunto)

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
   expediente y lanza una notificación (en macOS, con sonido).

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
```

## Uso

```bash
venv/bin/python3 monitorear_expediente.py             # revisa una vez y termina
venv/bin/python3 monitorear_expediente.py --cada 30   # revisa cada 30 min (Ctrl+C para salir)
```

Ejemplo de salida:

```
[2026-11-18 16:42] Sin cambios en Exp. 649/2025 (11 acuerdos).
+-------------------+--------------------------+--------------------------+------------------------------------------+
| Fecha Publicación | Secretaría               | Partes                   | Síntesis                                 |
+===================+==========================+==========================+==========================================+
| 09-Jul-2025       | SECRETARIA PRIMERA “A”   | ORAL DE ALIMENTOS.-      | Se radica.-                              |
+-------------------+--------------------------+--------------------------+------------------------------------------+
| ...               |                          |                          |                                          |
+-------------------+--------------------------+--------------------------+------------------------------------------+
| 03-Nov-2026       | SECRETARIA PRIMERA “A”   | ORAL DE ALIMENTOS.       | se recibe exhorto diligenciado.-574      |
+-------------------+--------------------------+--------------------------+------------------------------------------+
```

- Una sola revisión siempre imprime la tabla completa.
- Con `--cada`, la tabla se imprime al arrancar y después solo cuando hay cambios.

## Correrlo automáticamente (Raspberry Pi / Linux / macOS)

Con `cron`: ejecuta `crontab -e` y agrega una línea. Por ejemplo, cada 30
minutos de 7:00 a 21:59, de lunes a viernes:

```
*/30 7-21 * * 1-5 cd /home/pi/monitoreo-lista-acuerdos && venv/bin/python3 monitorear_expediente.py >> monitoreo.log 2>&1
```

Para ver el historial de revisiones:

```bash
tail -f monitoreo.log
```

> El script carga `.env` desde su propia carpeta, así que funciona aunque cron
> lo ejecute desde otro directorio.

## Configuración

### `.env` — expediente a monitorear (sí se sube a git)

| Variable | Qué es | Valor actual |
|---|---|---|
| `ADISON_ID_UNIDAD` | `value` del Órgano Jurisdiccional | `157` (Juzgado 3º Familiar Hermosillo) |
| `ADISON_ID_GRUPO_RAMO` | `data-value` del Ramo | `1` (FAMILIAR) |
| `ADISON_ID_CAT_RAMO` | `value` del Ramo (solo para armar el link) | `2` (FAMILIAR) |
| `ADISON_ID_TIPO_ASUNTO` | `value` del Tipo Asunto | `1` (EXPEDIENTE) |
| `ADISON_ASUNTO` | Número de asunto | `649` |
| `ADISON_ANIO` | Año del asunto | `2025` |
| `ADISON_BIS` | `value` de Bis (`0` = vacío, `1` = BIS, `3` = TER…) | `0` |

Para **monitorear otro expediente**, cambia estos valores. Los IDs salen de los
`<select>` del formulario: en la página, clic derecho sobre el campo >
**Inspeccionar** y busca el `<option>` correspondiente.

### `.env.local` — secretos (no se sube a git)

Tokens o contraseñas (por ejemplo, para avisos por Telegram) van en
`.env.local`. Si existe, sus valores tienen prioridad sobre los de `.env`.

## Archivos

| Archivo | Descripción |
|---|---|
| `monitorear_expediente.py` | Script principal |
| `.env` | Datos del expediente a monitorear |
| `.env.local` | Secretos (opcional, ignorado por git) |
| `estado_*.json` | Acuerdos ya vistos (se genera solo, ignorado por git) |
| `monitoreo.log` | Salida de cron (si lo configuras así, ignorado por git) |
| `requirements.txt` | Dependencias: `requests`, `python-dotenv` |
