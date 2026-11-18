# selenium-monitoreo-lista-acuerdos

Monitorea la [Lista de Acuerdos de ADISON](https://adison.stjsonora.gob.mx/Publicacion/ListaAcuerdos/)
(Poder Judicial del Estado de Sonora) para un expediente y avisa cuando se publica
un acuerdo nuevo. Expediente configurado en `.env`: **Exp. 649/2025, Juzgado
Tercero de Primera Instancia de lo Familiar de Hermosillo**.

No abre navegador: llama directamente al mismo endpoint que usa la página
(`/Controller/ActionController.php`, acción `BuscarByAsunto`).

## Instalación

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Uso

```bash
python3 monitorear_expediente.py             # revisa una vez y termina
python3 monitorear_expediente.py --cada 30   # revisa cada 30 minutos (Ctrl+C para salir)
```

- La **primera corrida** guarda los acuerdos actuales como base en
  `estado_<unidad>_<asunto>_<año>_<bis>.json` (no se sube a git).
- Las siguientes corridas comparan contra esa base e imprimen los acuerdos
  **nuevos** o **modificados**, con el link al expediente, y muestran una
  notificación de macOS con sonido.
- Si borras el archivo de estado, la siguiente corrida vuelve a tomar la base.

### Correrlo automáticamente con cron

`crontab -e` y agrega (revisa cada hora entre 8:00 y 20:00, de lunes a viernes):

```
0 8-20 * * 1-5 cd /ruta/al/proyecto && venv/wilsonenv/bin/python3 monitorear_expediente.py >> monitoreo.log 2>&1
```

## Monitorear otro expediente

Edita las variables `ADISON_*` en `.env` (este archivo sí se sube a git porque no
tiene secretos; cualquier token o contraseña va en `.env.local`, que no se sube).
Los IDs se
obtienen de los `<select>` del formulario en la página (clic derecho >
Inspeccionar):

| Variable | Campo en la página | Ejemplo |
|---|---|---|
| `ADISON_ID_UNIDAD` | `value` del Órgano Jurisdiccional | `157` |
| `ADISON_ID_GRUPO_RAMO` | `data-value` del Ramo | `1` (FAMILIAR) |
| `ADISON_ID_CAT_RAMO` | `value` del Ramo (solo para el link) | `2` (FAMILIAR) |
| `ADISON_ID_TIPO_ASUNTO` | `value` del Tipo Asunto | `1` (EXPEDIENTE) |
| `ADISON_ASUNTO` / `ADISON_ANIO` | No. de asunto | `649` / `2025` |
| `ADISON_BIS` | `value` de Bis (0 = vacío) | `0` |

