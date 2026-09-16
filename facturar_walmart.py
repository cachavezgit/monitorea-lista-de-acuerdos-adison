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

import sys
import time

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC

try:
    from webdriver_manager.chrome import ChromeDriverManager
    from selenium.webdriver.chrome.service import Service
    HAS_WEBDRIVER_MANAGER = True
except ImportError:
    HAS_WEBDRIVER_MANAGER = False

URL = "https://facturacion-clientes.walmart.com/"

# ---------- Datos fijos ----------
RFC = "CAFC730804DZ2"
CODIGO_POSTAL = "83293"
CORREO = "cachavezf@gmail.com"
REGIMEN_FISCAL = "Regimen Simplificado de Confianza"
USO_FACTURA = "Gastos en general"
FORMA_PAGO = "Tarjeta de crédito"


def esperar_y_click(wait, xpath, descripcion):
    try:
        elemento = wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
    except TimeoutException as exc:
        raise TimeoutException(
            f"No encontré el botón/elemento '{descripcion}' con XPath: {xpath}\n"
            "Inspecciona el sitio y ajusta este selector en el script."
        ) from exc
    elemento.click()
    return elemento


def esperar_elemento(wait, xpath, descripcion):
    try:
        return wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
    except TimeoutException as exc:
        raise TimeoutException(
            f"No encontré el campo '{descripcion}' con XPath: {xpath}\n"
            "Inspecciona el sitio y ajusta este selector en el script."
        ) from exc


def crear_driver(headless: bool):
    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
    if HAS_WEBDRIVER_MANAGER:
        return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    return webdriver.Chrome(options=options)


def facturar(numero_ticket: str, ultimos_4: str, headless: bool = False):
    driver = crear_driver(headless)
    wait = WebDriverWait(driver, 20)

    try:
        driver.get(URL)

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

        esperar_y_click(
            wait,
            "//button[contains(.,'Continuar') or contains(.,'Facturar') or contains(.,'Buscar')]",
            "Continuar/Facturar/Buscar (pantalla 1)",
        )

        # ---------- Modal "Importante" (si aparece) ----------
        try:
            aceptar_btn = WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(.,'Aceptar')]"))
            )
            aceptar_btn.click()
            print("Modal 'Importante' cerrado.")
        except TimeoutException:
            print("No apareció el modal 'Importante' (o ya estaba cerrado), continúo.")

        # ---------- Pantalla de datos fiscales ----------
        print("Llenando correo, régimen fiscal y uso de factura...")
        correo_input = esperar_elemento(
            wait, "//*[contains(text(),'Correo Electr')]/following::input[1]", "Correo Electrónico"
        )
        correo_input.clear()
        correo_input.send_keys(CORREO)

        regimen_select = Select(
            esperar_elemento(
                wait, "//*[contains(text(),'Régimen Fiscal')]/following::select[1]", "Régimen Fiscal"
            )
        )
        regimen_select.select_by_visible_text(REGIMEN_FISCAL)

        uso_select = Select(
            esperar_elemento(wait, "//*[contains(text(),'Uso Factura')]/following::select[1]", "Uso Factura")
        )
        uso_select.select_by_visible_text(USO_FACTURA)

        esperar_y_click(wait, "//button[contains(.,'Continuar')]", "Continuar (datos fiscales)")

        # ---------- Alerta "¿Están correctos todos sus datos?" ----------
        esperar_y_click(wait, "//button[contains(.,'Continuar')]", "Continuar (confirmación de datos)")

        # ---------- Forma de Pago -> Tarjeta de crédito ----------
        print("Seleccionando forma de pago...")
        forma_pago_select = Select(
            esperar_elemento(wait, "//*[contains(text(),'Forma de Pago')]/following::select[1]", "Forma de Pago")
        )
        forma_pago_select.select_by_visible_text(FORMA_PAGO)

        # ---------- Click final en Facturar ----------
        esperar_y_click(wait, "//button[contains(.,'Facturar')]", "Facturar (paso final)")

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
    facturar(numero_ticket, ultimos_4)
