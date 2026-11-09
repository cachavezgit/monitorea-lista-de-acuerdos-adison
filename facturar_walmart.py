"""
Automatización de facturación en https://facturacion-clientes.walmart.com/

Requisitos:
    pip install selenium webdriver-manager

Uso:
    python facturar_walmart.py
    (te pedirá el número largo del ticket y los últimos 4 dígitos)

IMPORTANTE: Como el sitio es una app React (SPA), los selectores XPath usados
abajo se basan en el texto visible de las etiquetas y en el orden de los
campos. Si algún paso falla, el navegador se queda abierto (no headless) y el
error te dice exactamente qué localizador no encontró nada, para que hagas
click derecho > "Inspeccionar" sobre ese campo/botón y ajustes el XPath.
"""

import os
import sys
import time

from dotenv import load_dotenv
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC

try:
    from webdriver_manager.chrome import ChromeDriverManager
    from selenium.webdriver.chrome.service import Service
    HAS_WEBDRIVER_MANAGER = True
except ImportError:
    HAS_WEBDRIVER_MANAGER = False

URL = "https://facturacion-clientes.walmart.com/"

# ---------- Datos fijos (desde .env, ver .env.example) ----------
load_dotenv()

VARS_REQUERIDAS = [
    "RFC", "CODIGO_POSTAL", "RAZON_SOCIAL", "CORREO",
    "REGIMEN_FISCAL", "USO_FACTURA", "FORMA_PAGO",
]
faltantes = [v for v in VARS_REQUERIDAS if not os.getenv(v)]
if faltantes:
    sys.exit(
        f"Faltan variables en .env: {', '.join(faltantes)}. "
        "Copia .env.example a .env y complétalo con tus datos."
    )

RFC = os.getenv("RFC")
CODIGO_POSTAL = os.getenv("CODIGO_POSTAL")
RAZON_SOCIAL = os.getenv("RAZON_SOCIAL")
CORREO = os.getenv("CORREO")
REGIMEN_FISCAL = os.getenv("REGIMEN_FISCAL")
USO_FACTURA = os.getenv("USO_FACTURA")
FORMA_PAGO = os.getenv("FORMA_PAGO")


def esperar_y_click(driver, wait, xpath, descripcion):
    try:
        elemento = wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
    except TimeoutException as exc:
        raise TimeoutException(
            f"No encontré el botón/elemento '{descripcion}' con XPath: {xpath}\n"
            "Inspecciona el sitio y ajusta este selector en el script."
        ) from exc
    # Clic vía JavaScript en vez de elemento.click(): el clic "físico" de Selenium
    # (basado en coordenadas) a veces no surtía efecto en los botones type="submit"
    # de este sitio; el clic por JS invoca el mismo evento sin depender de la posición.
    driver.execute_script("arguments[0].click();", elemento)
    return elemento


def click_hasta_avanzar(wait, driver, click_xpath, descripcion, xpath_avance, intentos=2, espera_por_intento=25):
    """Da clic y confirma que la página avanzó (aparece xpath_avance); si no, reintenta el clic.

    El clic de Selenium en los botones "Continuar"/"Aceptar" de este sitio a veces no
    surte efecto aunque no lance ningún error (parece un problema de timing del SPA),
    mientras que un clic humano sí funciona siempre. Reintentar el clic es un workaround
    seguro para estos pasos porque no generan la factura ni tienen efectos secundarios.
    """
    for intento in range(1, intentos + 1):
        esperar_y_click(driver, wait, click_xpath, descripcion)
        try:
            WebDriverWait(driver, espera_por_intento).until(
                EC.presence_of_element_located((By.XPATH, xpath_avance))
            )
            return
        except TimeoutException:
            if intento == intentos:
                raise TimeoutException(
                    f"'{descripcion}' no logró avanzar la página tras {intentos} clics."
                )
            print(f"'{descripcion}' no avanzó, reintentando clic ({intento}/{intentos})...")


def esperar_elemento(wait, xpath, descripcion):
    try:
        return wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
    except TimeoutException as exc:
        raise TimeoutException(
            f"No encontré el campo '{descripcion}' con XPath: {xpath}\n"
            "Inspecciona el sitio y ajusta este selector en el script."
        ) from exc


def llenar_campo(wait, xpath, valor, descripcion, intentos=3):
    """Escribe `valor` en el input y confirma que el valor quedó ahí; si no, reintenta.

    Justo después de cerrarse el modal de "datos personales" la SPA a veces vuelve a
    renderizar el formulario, lo que puede vaciar lo que ya se había escrito. Verificar
    el valor final evita enviar el formulario con estos campos en blanco.
    """
    for intento in range(1, intentos + 1):
        elemento = esperar_elemento(wait, xpath, descripcion)
        elemento.clear()
        elemento.send_keys(valor)
        time.sleep(0.5)
        if elemento.get_attribute("value") == valor:
            return
        if intento == intentos:
            raise RuntimeError(
                f"'{descripcion}' no conservó el valor tras {intentos} intentos "
                f"(quedó: {elemento.get_attribute('value')!r})."
            )
        print(f"'{descripcion}' se vació después de escribirlo, reintentando ({intento}/{intentos})...")


def seleccionar_opcion(driver, wait, select_xpath, texto, descripcion):
    """Selecciona `texto` en un <select>, esperando a que esa opción exista.

    Estos combos (Régimen Fiscal, Uso Factura, Forma de Pago) cargan sus <option>
    de forma asíncrona desde el backend (p.ej. la llamada ObtenerCatRegimenFiscal),
    así que el <select> puede existir en el DOM antes de tener la opción deseada.
    """
    select_element = esperar_elemento(wait, select_xpath, descripcion)
    try:
        WebDriverWait(driver, 20).until(
            lambda d: any(o.text.strip() == texto for o in Select(select_element).options)
        )
    except TimeoutException as exc:
        opciones = [o.text.strip() for o in Select(select_element).options]
        raise TimeoutException(
            f"El combo '{descripcion}' nunca cargó la opción '{texto}'. "
            f"Opciones disponibles ahora mismo: {opciones}"
        ) from exc
    Select(select_element).select_by_visible_text(texto)


def crear_driver(headless: bool):
    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
    # El sitio parece detectar que el navegador está automatizado (navigator.webdriver)
    # y bloquear en silencio la validación del ticket cuando el clic viene de Selenium
    # aunque el clic manual con el mismo navegador sí funciona. Ocultamos esas huellas.
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    if HAS_WEBDRIVER_MANAGER:
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    else:
        driver = webdriver.Chrome(options=options)

    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
    )
    return driver


def facturar(numero_ticket: str, ultimos_4: str, forma_pago: str = FORMA_PAGO, headless: bool = False):
    driver = crear_driver(headless)
    wait = WebDriverWait(driver, 20)

    try:
        driver.get(URL)

        # ---------- Modal inicial "CFDI VERSION 4.0" (si aparece) ----------
        try:
            aceptar_inicial = WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(.,'Aceptar')]"))
            )
            driver.execute_script("arguments[0].click();", aceptar_inicial)
            print("Modal 'CFDI VERSION 4.0' cerrado.")
        except TimeoutException:
            print("No apareció el modal inicial de CFDI (o ya estaba cerrado), continúo.")

        # ---------- Landing: click en "Obtener factura" ----------
        esperar_y_click(driver, wait, "//*[self::button or self::a][contains(.,'Obtener factura')]", "Obtener factura")

        # ---------- Pantalla 1: Facturar / Refacturar ----------
        print("Llenando RFC, código postal, ticket y últimos 4 dígitos...")
        inputs = wait.until(
            EC.presence_of_all_elements_located(
                (By.CSS_SELECTOR, "form input[type='text'], form input:not([type])")
            )
        )
        if len(inputs) < 4:
            raise RuntimeError(
                f"Esperaba 4 campos de texto en la pantalla inicial, encontré {len(inputs)}. "
                "Inspecciona el sitio y ajusta el selector CSS."
            )
        inputs[0].send_keys(RFC)
        inputs[1].send_keys(CODIGO_POSTAL)
        inputs[2].send_keys(numero_ticket)
        inputs[3].send_keys(ultimos_4)
        inputs[3].send_keys(Keys.TAB)  # dispara el blur/validación del último campo
        time.sleep(2)  # da tiempo a la validación async del ticket antes de continuar

        # Un solo clic: el backend valida el ticket ("Procesando...") y puede tardar
        # bastante. Reintentar el clic aquí cancela esa validación en curso, así que
        # solo esperamos (sin volver a dar clic) a que aparezca la pantalla siguiente.
        # Usamos el id real del botón (form_btn_accept) en vez de buscar por texto,
        # porque el XPath por texto "Continuar" podía estar aterrizando en otro
        # elemento oculto de la página que no era el botón visible.
        try:
            boton_continuar = wait.until(EC.element_to_be_clickable((By.ID, "form_btn_accept")))
        except TimeoutException as exc:
            raise TimeoutException(
                "No encontré el botón 'Continuar' (id=form_btn_accept) en la pantalla 1."
            ) from exc
        driver.execute_script("arguments[0].click();", boton_continuar)
        try:
            WebDriverWait(driver, 60).until(
                EC.presence_of_element_located((By.XPATH, "//*[contains(text(),'Razón Social')]"))
            )
        except TimeoutException as exc:
            raise TimeoutException(
                "La pantalla de datos fiscales no apareció tras 60s de 'Procesando...'. "
                "Puede que el ticket/últimos 4 dígitos sean inválidos."
            ) from exc

        # ---------- Pantalla de datos fiscales (tarda unos segundos en cargar) ----------
        # ---------- Modal "Importante: Para proteger sus datos personales..." ----------
        # El formulario de datos fiscales ya está renderizado detrás del modal y su
        # propio botón de envío también se llama "Aceptar" (mismo id="form_btn_accept"),
        # así que hay que excluirlo explícitamente para no hacer clic en el botón
        # equivocado (el del formulario, escondido detrás del modal).
        modal_aceptar_xpath = "//button[contains(.,'Aceptar') and not(@id='form_btn_accept')]"
        try:
            aceptar_datos_personales = WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable((By.XPATH, modal_aceptar_xpath))
            )
            driver.execute_script("arguments[0].click();", aceptar_datos_personales)
            WebDriverWait(driver, 10).until(EC.invisibility_of_element_located((By.XPATH, modal_aceptar_xpath)))
            print("Modal 'protección de datos personales' cerrado.")
        except TimeoutException:
            print("No apareció el modal de datos personales (o ya estaba cerrado), continúo.")

        print("Llenando razón social, correo, régimen fiscal y uso de factura...")
        llenar_campo(
            wait, "//*[contains(text(),'Razón Social')]/following::input[1]", RAZON_SOCIAL, "Razón Social"
        )
        llenar_campo(
            wait, "//*[contains(text(),'Correo Electr')]/following::input[1]", CORREO, "Correo Electrónico"
        )

        seleccionar_opcion(
            driver, wait, "//*[contains(text(),'Régimen Fiscal')]/following::select[1]",
            REGIMEN_FISCAL, "Régimen Fiscal",
        )

        seleccionar_opcion(
            driver, wait, "//*[contains(text(),'Uso Factura')]/following::select[1]",
            USO_FACTURA, "Uso Factura",
        )

        click_hasta_avanzar(
            wait, driver, "//button[contains(.,'Aceptar')]", "Aceptar (datos fiscales)",
            "//*[contains(text(),'correctos todos sus datos')]",
        )

        # ---------- Alerta "¿Están correctos todos sus datos?" ----------
        click_hasta_avanzar(
            wait, driver, "//button[contains(.,'Continuar')]", "Continuar (confirmación de datos)",
            "//*[contains(text(),'Forma de Pago')]",
        )

        # ---------- Forma de Pago -> Tarjeta de crédito ----------
        print("Seleccionando forma de pago...")
        seleccionar_opcion(
            driver, wait, "//*[contains(text(),'Forma de Pago')]/following::select[1]",
            forma_pago, "Forma de Pago",
        )

        click_hasta_avanzar(
            wait,
            driver,
            "//button[contains(.,'Continuar') or contains(.,'Facturar')]",
            "Continuar (forma de pago)",
            "//*[contains(text(),'PDF') or contains(text(),'correo electrónico')]",
        )

        # ---------- Pantalla de entrega: "Enviar a correo electrónico" ya viene seleccionado ----------
        # ---------- Click final en Facturar (genera la factura real) ----------
        esperar_y_click(driver, wait, "//button[contains(.,'Facturar')]", "Facturar (paso final)")

        print("Factura generada correctamente.")
        time.sleep(5)  # deja tiempo para ver el resultado antes de cerrar

    except Exception as exc:
        print(f"\nERROR: {exc}\n", file=sys.stderr)
        if not headless:
            input("El navegador quedó abierto para que inspecciones el problema. Presiona Enter para cerrarlo...")
        raise
    finally:
        driver.quit()


if __name__ == "__main__":
    numero_ticket = input("Número largo del ticket: ").strip()
    ultimos_4 = input("Últimos 4 dígitos: ").strip()
    fue_tarjeta_credito = input("¿Fue con Tarjeta de Crédito? (S/N) default S: ").strip().upper() or "S"
    forma_pago = "Tarjeta de crédito" if fue_tarjeta_credito == "S" else "Tarjeta de débito"

    facturar(numero_ticket, ultimos_4, forma_pago=forma_pago)
