# selenium-facturar-walmart

Automatiza el proceso de facturación en https://facturacion-clientes.walmart.com/
usando Selenium: llena el ticket, los datos fiscales y la forma de pago hasta
generar la factura.

## Requisitos

- Python 3.8+
- Google Chrome instalado

## Instalación

```bash
# Crear entorno virtual
python3 -m venv venv

# Activar el entorno virtual
source venv/bin/activate      # macOS / Linux
venv\Scripts\activate         # Windows

# Instalar dependencias
pip install -r requirements.txt
```

### Configurar tus datos

Copia la plantilla y complétala con tus datos fiscales (este archivo `.env`
no se sube a git):

```bash
cp .env.example .env
```

```
RFC=
CODIGO_POSTAL=
RAZON_SOCIAL=
CORREO=
REGIMEN_FISCAL=
USO_FACTURA=
FORMA_PAGO=
```

## Uso

Con el entorno virtual activado:

```bash
python3 facturar_walmart.py
```

El script te pedirá el número largo del ticket y los últimos 4 dígitos, abrirá
Chrome y completará el flujo de facturación automáticamente. Si algún paso
falla, el navegador se queda abierto y la terminal indica exactamente qué
campo o botón no se encontró.

Para salir del entorno virtual cuando termines:

```bash
deactivate
```
