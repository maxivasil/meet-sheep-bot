#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
===============================================================================
Meet Sheep Bot - Bot de Asistencia Automática para Google Meet
===============================================================================
Descripción:
  Script en Python con Selenium que se conecta a una clase de Google Meet,
  desactiva cámara y micrófono de antemano, ingresa a la reunión, abre el panel
  de chat y monitorea los mensajes en busca de padrones/DNIs (números de 5 a 8 dígitos).
  Cuando detecta que al menos 3 usuarios distintos han enviado su número, el bot
  envía automáticamente tu padrón, registra la asistencia con marca de tiempo
  en un archivo de log y cierra el navegador.
===============================================================================
"""

import os
import re
import sys
import time
import logging
import shutil
from datetime import datetime, timedelta
from typing import Set, List

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    ElementClickInterceptedException,
    WebDriverException
)
from webdriver_manager.chrome import ChromeDriverManager

# Cargar variables de entorno si se utiliza un archivo .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

def get_default_chrome_user_data_dir() -> str:
    """
    Retorna la ruta por defecto del directorio User Data de Chrome según el sistema operativo.
    """
    if sys.platform.startswith("win"):
        return os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data")
    elif sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/Google/Chrome")
    else:
        return os.path.expanduser("~/.config/google-chrome")


# ==============================================================================
# CONFIGURACIÓN DEL BOT - MODIFICA ESTOS VALORES SEGÚN TU CASO DE USO
# O UTILIZA UN ARCHIVO .env EN LA RAÍZ DEL PROYECTO
# ==============================================================================

# 1. Tu número de padrón o DNI a enviar en el chat
PADRON = os.getenv("MEET_PADRON", "12345678")

# 2. URL de la reunión de Google Meet
MEET_URL = os.getenv("MEET_URL", "https://meet.google.com/abc-defg-hij")

# 3. Hora programada de inicio (Opcional)
#    Formato 24hs "HH:MM" (Ej: "06:30" o "08:00").
#    Si está vacío "", el bot ingresará inmediatamente al ejecutarse.
SCHEDULED_TIME = os.getenv("MEET_SCHEDULED_TIME", "")

# 4. Ruta a la carpeta User Data de tu perfil real de Chrome (para mantener la sesión iniciada)
CHROME_USER_DATA_DIR = os.getenv(
    "CHROME_USER_DATA_DIR", 
    get_default_chrome_user_data_dir()
)

# 5. Nombre de la carpeta de perfil ("Default", "Profile 1", "Profile 2", etc.)
CHROME_PROFILE_DIRECTORY = os.getenv("CHROME_PROFILE_DIRECTORY", "Default")

# 6. Nombre a ingresar si Google Meet solicita "¿Cuál es tu nombre?" antes de unirse
DISPLAY_NAME = os.getenv("MEET_DISPLAY_NAME", "Estudiante")

# 6. Modo de perfil de Chrome:
#    - False (RECOMENDADO): Utiliza tu perfil real de Chrome directamente. Conserva la sesión e inicio
#      de sesión de Google autenticado (evita el mensaje "No puedes unirte a esta videollamada").
#      Requiere cerrar las ventanas de Chrome antes de lanzar el bot.
#    - True: Clona el perfil para poder ejecutar el bot con Chrome abierto (puede ser tratado como invitado sin sesión).
USE_PROFILE_CLONE = os.getenv("USE_PROFILE_CLONE", "false").lower() in ("true", "1", "t")

# 7. Parámetros de control de asistencia
MIN_UNIQUE_NUMBERS = 5         # Cantidad de números distintos de otros usuarios para confirmar toma de asistencia
REGEX_NUMERIC_PATTERN = r'\b\d{5,8}\b'  # Expresión regular para capturar DNIs/Padrones (5 a 8 dígitos)

# 6. Tiempos de espera (en segundos)
TIMEOUT_JOIN_BUTTON = 45       # Espera máxima para encontrar el botón de ingreso
TIMEOUT_CHAT_PANEL = 20        # Espera máxima para abrir el chat
TIMEOUT_CHAT_INPUT = 15        # Espera máxima para encontrar la caja de texto del chat
CHECK_INTERVAL_SECONDS = 3     # Frecuencia de escaneo del chat
MAX_MONITORING_TIME_SECONDS = 10800 # Tiempo máximo de monitoreo antes de finalizar (3 horas)

# 7. Ruta del archivo de registro de asistencia
LOG_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "asistencia.log")

# ==============================================================================
# CONFIGURACIÓN DE LOGGING
# ==============================================================================

logger = logging.getLogger("MeetSheepBot")
logger.setLevel(logging.INFO)

# Formato de logs
formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

# Handler de consola
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# Handler de archivo para registro de asistencia
file_handler = logging.FileHandler(LOG_FILE_PATH, encoding="utf-8")
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)


def prepare_user_data_dir() -> str:
    """
    Prepara el directorio de datos de usuario dedicado para el bot (~/.config/google-chrome-bot).
    Evita conflictos de bloqueo (SingletonLock) con tu navegador principal y mantiene
    tu inicio de sesión de Google guardado de forma permanente para el bot.
    """
    bot_user_data_dir = os.path.expanduser("~/.config/google-chrome-bot")
    os.makedirs(bot_user_data_dir, exist_ok=True)
    
    # Eliminar posibles bloqueos residuales de ejecuciones previas
    for item in ["SingletonLock", "SingletonSocket", "SingletonCookie", "LOCK"]:
        stale_lock = os.path.join(bot_user_data_dir, item)
        if os.path.exists(stale_lock) or os.path.islink(stale_lock):
            try:
                os.unlink(stale_lock)
            except Exception:
                pass

    logger.info(f"Perfil del bot inicializado en: {bot_user_data_dir}")
    return bot_user_data_dir


def is_user_logged_in_to_google(driver: webdriver.Chrome) -> bool:
    """
    Comprueba de forma robusta si la cuenta de Google está actualmente logueada.
    """
    try:
        url = driver.current_url.lower()
        # Si la URL contiene signin, identifier, challenge, pwd, el usuario aún se está autenticando
        if any(kw in url for kw in ["signin", "identifier", "challenge", "pwd", "v3/signin"]):
            return False

        body_text = driver.find_element(By.TAG_NAME, "body").text.lower()
        if "inicia sesión" in body_text or "sign in" in body_text or "elije una cuenta" in body_text:
            return False

        # Verificar presencia de elementos de cuenta o redirección a dashboard
        if "myaccount.google.com" in url or "google.com/account" in url:
            return True

        # Si estamos en accounts.google.com pero sin parámetros de signin
        if "accounts.google.com" in url and not any(kw in url for kw in ["signin", "identifier", "challenge"]):
            return True

    except Exception:
        pass
    return False


def ensure_google_login(driver: webdriver.Chrome, timeout: int = 180) -> bool:
    """
    Verifica si el perfil del bot tiene la sesión iniciada en Google.
    Si no la tiene, abre la página de inicio de sesión de Google y espera a que el usuario
    inicie sesión completamente (email + contraseña + 2FA si aplica).
    """
    logger.info("Verificando estado de la sesión de Google en el bot...")
    driver.get("https://myaccount.google.com")
    time.sleep(3)

    if is_user_logged_in_to_google(driver):
        logger.info("¡Sesión de Google activa detectada en el bot!")
        return True

    logger.info("=================================================================")
    logger.info("¡ATENCIÓN! Se requiere iniciar sesión en Google por ÚNICA VEZ.")
    logger.info("Por favor ingresa tu email y contraseña en la ventana de Chrome abierta.")
    logger.info("Una vez completado el inicio de sesión, quedará guardado PERMANENTEMENTE.")
    logger.info(f"Esperando inicio de sesión (máximo {timeout} segundos)...")
    logger.info("=================================================================")

    start_time = time.time()
    while time.time() - start_time < timeout:
        if is_user_logged_in_to_google(driver):
            logger.info("=================================================================")
            logger.info("¡Inicio de sesión en Google completado con éxito!")
            logger.info("Credenciales guardadas correctamente en el perfil del bot.")
            logger.info("=================================================================")
            time.sleep(2)
            return True
        time.sleep(3)

    logger.warning("Tiempo de espera para inicio de sesión agotado. Intentando continuar hacia Meet...")
    return False


def handle_name_input_if_present(driver: webdriver.Chrome, name: str) -> bool:
    """
    Verifica si Google Meet solicita un nombre para ingresar ("¿Cuál es tu nombre?")
    y lo autocompleta antes de unirse a la reunión.
    """
    logger.info("Verificando si Google Meet solicita ingresar nombre de usuario...")
    time.sleep(2)
    name_input_xpaths = [
        "//input[@type='text' and (contains(@aria-label, 'nombre') or contains(@aria-label, 'name') or contains(@aria-label, 'Nombre') or contains(@aria-label, 'Name'))]",
        "//input[@type='text' and (contains(@placeholder, 'nombre') or contains(@placeholder, 'name') or contains(@placeholder, 'Nombre') or contains(@placeholder, 'Name'))]",
        "//input[@type='text' and @jsname='YPqjbf']",
        "//input[@type='text']"
    ]

    for xpath in name_input_xpaths:
        try:
            elements = driver.find_elements(By.XPATH, xpath)
            for elem in elements:
                if elem.is_displayed() and elem.is_enabled():
                    logger.info(f"Campo de nombre detectado. Autocompletando con: '{name}'")
                    elem.click()
                    time.sleep(0.5)
                    elem.clear()
                    elem.send_keys(name)
                    time.sleep(0.5)
                    elem.send_keys(Keys.ENTER)
                    logger.info("Nombre enviado exitosamente.")
                    time.sleep(2)
                    return True
        except Exception:
            continue

    logger.info("No se requirió ingreso manual de nombre.")
def wait_for_scheduled_time(scheduled_time_str: str):
    """
    Si se especifica un horario en formato 'HH:MM' (ej: '06:30'), el script esperará pacientemente
    hasta que el reloj alcance dicha hora local antes de iniciar Chrome.
    """
    if not scheduled_time_str or not scheduled_time_str.strip():
        return

    try:
        parts = scheduled_time_str.strip().split(":")
        target_hour = int(parts[0])
        target_minute = int(parts[1])
    except Exception:
        logger.warning(f"Formato de horario no válido: '{scheduled_time_str}'. Se requiere formato 24hs 'HH:MM' (ej. '06:30'). Se omitirá la espera.")
        return

    now = datetime.now()
    target_dt = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)

    # Si la hora objetivo ya pasó hoy (ej. son las 23:00 y programó 06:30), la meta es mañana a las 06:30
    if target_dt <= now:
        target_dt += timedelta(days=1)

    time_remaining = (target_dt - now).total_seconds()
    hours, remainder = divmod(int(time_remaining), 3600)
    minutes, seconds = divmod(remainder, 60)

    logger.info("=================================================================")
    logger.info(f"PROGRAMACIÓN ACTIVADA: El bot esperará hasta las {target_dt.strftime('%H:%M')} hs ({target_dt.strftime('%d/%m/%Y')})")
    logger.info(f"Hora actual: {now.strftime('%H:%M:%S')} | Tiempo restante: {hours}h {minutes}m {seconds}s")
    logger.info("El navegador Chrome NO se abrirá hasta llegar a la hora programada.")
    logger.info("Puedes dejar el script corriendo y dormir. Presiona Ctrl+C para cancelar.")
    logger.info("=================================================================")

    last_log_time = time.time()
    while datetime.now() < target_dt:
        time.sleep(5)
        # Registrar una actualización informativa en consola cada 5 minutos
        if time.time() - last_log_time >= 300:
            remaining = (target_dt - datetime.now()).total_seconds()
            if remaining > 0:
                h, rem = divmod(int(remaining), 3600)
                m, s = divmod(rem, 60)
                logger.info(f"Esperando inicio programado ({target_dt.strftime('%H:%M')})... Tiempo restante: {h}h {m}m {s}s")
            last_log_time = time.time()

    logger.info("=================================================================")
    logger.info(f"¡Llegó la hora programada ({target_dt.strftime('%H:%M')} hs)! Iniciando navegador y proceso de ingreso...")
    logger.info("=================================================================")


def setup_chrome_options() -> Options:
    """
    Configura y retorna las opciones de Chrome para el perfil dedicado del bot.
    """
    options = Options()

    bot_user_data_dir = prepare_user_data_dir()
    options.add_argument(f"--user-data-dir={bot_user_data_dir}")
    options.add_argument("--profile-directory=Default")

    # Flags para desactivar cámara/micrófono de antemano y evitar diálogos de permisos
    options.add_argument("--use-fake-ui-for-media-stream")
    options.add_argument("--use-fake-device-for-media-stream")
    options.add_argument("--mute-audio")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-infobars")
    
    # Flags anti-detección de automatización y compatibilidad
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument("--remote-allow-origins=*")

    # Optimizaciones de rendimiento y compatibilidad
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--start-maximized")

    return options


def join_meet(driver: webdriver.Chrome) -> bool:
    """
    Navega a la URL de Google Meet e intenta ingresar a la clase.
    """
    logger.info(f"Navegando a la reunión: {MEET_URL}")
    driver.get(MEET_URL)
    time.sleep(3)

    # Verificar si Google Meet rechazó el acceso por falta de autenticación
    try:
        page_text = driver.find_element(By.TAG_NAME, "body").text
        if "No puedes unirte" in page_text or "You can't join" in page_text:
            logger.error("=================================================================")
            logger.error("ERROR DE ACCESO: Google Meet mostró 'No puedes unirte a esta videollamada'.")
            logger.error("Causas principales:")
            logger.error(" 1. Esta reunión requiere iniciar sesión con tu cuenta de Google/institucional.")
            logger.error(" 2. El perfil clonado no transfiere credenciales encriptadas en Linux.")
            logger.error("Solución recomendada:")
            logger.error(" - CIERRA todas las ventanas de Chrome antes de ejecutar el bot.")
            logger.error(" - Asegúrate de que 'USE_PROFILE_CLONE = False' para usar tu perfil real directamente.")
            logger.error("=================================================================")
            return False
    except Exception:
        pass

    # 1. Autocompletar el nombre de usuario si Google Meet lo solicita
    handle_name_input_if_present(driver, DISPLAY_NAME)

    # 2. Apagar micrófono y cámara EN LA PANTALLA PREVIA antes de solicitar unirse
    try:
        body = driver.find_element(By.TAG_NAME, "body")
        body.send_keys(Keys.CONTROL + "d")
        time.sleep(0.5)
        body.send_keys(Keys.CONTROL + "e")
        logger.info("Cámara y micrófono desactivados previamente en la pantalla de vista previa.")
    except Exception as e:
        logger.debug(f"No se pudieron enviar los atajos previos: {e}")

    # Palabras clave en minúsculas para identificar el botón de ingreso a la reunión
    join_keywords = [
        "unir", "unirme", "unirse", "unirte", "join", "pedir", "solicitar", "volver", "entrar", "reincorporar"
    ]

    join_button = None
    logger.info("Buscando el botón para ingresar a la reunión...")

    start_time = time.time()
    while time.time() - start_time < TIMEOUT_JOIN_BUTTON:
        # 1. Verificar si ya estamos dentro de la llamada activa
        try:
            leave_btns = driver.find_elements(By.XPATH, "//button[contains(@aria-label, 'Salir de la llamada') or contains(@aria-label, 'Leave call') or contains(@aria-label, 'Colgar')]")
            if len(leave_btns) > 0 and leave_btns[0].is_displayed():
                logger.info("¡Se detectó que ya estás dentro de la llamada!")
                return True
        except Exception:
            pass

        # 2. Inspeccionar todos los botones de la página de forma rápida en Python
        try:
            all_buttons = driver.find_elements(By.TAG_NAME, "button")
            for btn in all_buttons:
                if not btn.is_displayed() or not btn.is_enabled():
                    continue

                btn_text = (btn.text or "").strip().lower()
                aria_label = (btn.get_attribute("aria-label") or "").strip().lower()
                jsname = btn.get_attribute("jsname") or ""

                # Verificar si el texto del botón, aria-label o jsname coinciden
                if any(kw in btn_text for kw in join_keywords) or any(kw in aria_label for kw in join_keywords) or jsname in ["Q4luWd", "j6lhVc"]:
                    join_button = btn
                    logger.info(f"Botón de ingreso localizado con éxito. Texto: '{btn.text}' | Aria: '{aria_label}' | jsname: '{jsname}'")
                    break

            if join_button:
                break
        except Exception:
            pass

        # 3. Respaldo por XPath redundante
        if not join_button:
            xpath_fallback = "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZÁÉÍÓÚ', 'abcdefghijklmnopqrstuvwxyzáéíóú'), 'unir') or contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'join') or contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'pedir') or contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'solicitar') or @jsname='Q4luWd']"
            try:
                elements = driver.find_elements(By.XPATH, xpath_fallback)
                for elem in elements:
                    if elem.is_displayed() and elem.is_enabled():
                        join_button = elem
                        logger.info(f"Botón de ingreso localizado vía XPath fallback.")
                        break
            except Exception:
                pass

        if join_button:
            break

        time.sleep(1)

    if not join_button:
        logger.error("No se encontró el botón de unirse a la reunión dentro del tiempo límite.")
        return False

    # Pequeña pausa para asegurar la estabilidad antes del click
    time.sleep(1)
    try:
        join_button.click()
        logger.info("Click realizado en el botón de unirse a la llamada.")
    except Exception:
        logger.warning("El click directo falló. Intentando click mediante JavaScript...")
        driver.execute_script("arguments[0].click();", join_button)

    time.sleep(2)
    return True


def ensure_chat_open(driver: webdriver.Chrome) -> bool:
    """
    Verifica si el panel de chat está visible y, si no lo está, interactúa para abrirlo.
    Evita hacer click en el botón si el campo de texto del chat ya está desplegado.
    """
    # 1. Comprobación directa: Si la caja de texto del chat (textarea) está visible, el chat está 100% abierto
    try:
        textareas = driver.find_elements(By.TAG_NAME, "textarea")
        for ta in textareas:
            if ta.is_displayed():
                return True
    except Exception:
        pass

    # 2. Comprobación secundaria por contenedores de chat
    chat_panel_xpaths = [
        "//div[@aria-live='polite']",
        "//div[contains(@aria-label, 'Chat') or contains(@aria-label, 'chat')]",
        "//div[@jsname='z3859']"
    ]

    for xpath in chat_panel_xpaths:
        try:
            elements = driver.find_elements(By.XPATH, xpath)
            if len(elements) > 0 and any(e.is_displayed() for e in elements):
                return True
        except Exception:
            continue

    logger.info("El panel de chat no está visible. Intentando abrirlo...")
    wait = WebDriverWait(driver, TIMEOUT_CHAT_PANEL)

    # 3. Intentar abrir el chat mediante el botón
    chat_button_xpaths = [
        "//button[contains(@aria-label, 'Chat con todos') or contains(@aria-label, 'Chat with everyone') or contains(@aria-label, 'Chat')]",
        "//button[@jsname='A533Id']",
        "//button[descendant::i[contains(text(), 'chat') or contains(@class, 'chat')]]"
    ]

    opened = False
    for xpath in chat_button_xpaths:
        try:
            btn = wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
            btn.click()
            logger.info("Click en el botón del panel de chat realizado.")
            opened = True
            break
        except Exception:
            continue

    if not opened:
        logger.warning("Intentando abrir el chat mediante atajo de teclado (Ctrl + Alt + C)...")
        try:
            body = driver.find_element(By.TAG_NAME, "body")
            body.send_keys(Keys.CONTROL + Keys.ALT + "c")
            opened = True
        except Exception as e:
            logger.error(f"Error al enviar atajo de chat: {e}")

    time.sleep(2)
    return opened


def scan_chat_for_numbers(driver: webdriver.Chrome) -> List[str]:
    """
    Escanea todo el contenido del panel de chat y extrae todos los números
    de 5 a 8 dígitos encontrados (DNIs o Padrones).
    """
    extracted_numbers: List[str] = []

    # Selectores para obtener contenedores de mensajes del chat
    chat_container_xpaths = [
        "//div[@aria-live='polite']",
        "//div[contains(@class, 'kw520e') or contains(@class, 'z3859')]",
        "//div[contains(@data-message-text, '')]/ancestor::div[contains(@aria-live, 'polite')]"
    ]

    chat_text = ""
    for xpath in chat_container_xpaths:
        try:
            containers = driver.find_elements(By.XPATH, xpath)
            for container in containers:
                if container.is_displayed():
                    chat_text += " " + container.text
        except Exception:
            continue

    if not chat_text:
        # Fallback: intentar leer todo el body si el contenedor específico cambia de clase
        try:
            chat_text = driver.find_element(By.TAG_NAME, "body").text
        except Exception:
            pass

    # Aplicar expresión regular para extraer padrones/DNIs
    matches = re.findall(REGEX_NUMERIC_PATTERN, chat_text)
    for match in matches:
        extracted_numbers.append(match.strip())

    return extracted_numbers


def send_attendance(driver: webdriver.Chrome, padron: str) -> bool:
    """
    Escribe el número de padrón en el campo de texto del chat, presiona Enter
    y registra la hora exacta en el log de forma instantánea.
    """
    logger.info(f"Procediendo a enviar el número de padrón: {padron}")
    chat_input = None

    # 1. Búsqueda instantánea directa por tag <textarea> (evita retrasos de timeout de 15s)
    try:
        textareas = driver.find_elements(By.TAG_NAME, "textarea")
        for ta in textareas:
            if ta.is_displayed():
                chat_input = ta
                break
    except Exception:
        pass

    # 2. Respaldo por XPath con timeout corto de 3s si la búsqueda directa no lo encuentra
    if not chat_input:
        wait = WebDriverWait(driver, 3)
        input_xpaths = [
            "//textarea",
            "//textarea[contains(@aria-label, 'Enviar') or contains(@aria-label, 'Send')]",
            "//textarea[@name='chatMessage']"
        ]
        for xpath in input_xpaths:
            try:
                elem = wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
                if elem and elem.is_displayed():
                    chat_input = elem
                    break
            except TimeoutException:
                continue

    if not chat_input:
        logger.error("No se pudo localizar el campo de texto del chat para enviar el padrón.")
        return False

    try:
        # Escribir y enviar el número de padrón
        chat_input.click()
        time.sleep(1)
        chat_input.clear()
        chat_input.send_keys(padron)
        time.sleep(2)
        chat_input.send_keys(Keys.ENTER)
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        success_message = f"=== PRESENTE ENVIADO CON ÉXITO === | Padrón: {padron} | Hora: {timestamp}"
        logger.info(success_message)

        time.sleep(1)
        return True

    except Exception as e:
        logger.error(f"Error al intentar enviar el mensaje en el chat: {e}")
        return False


def get_participant_count(driver: webdriver.Chrome) -> int:
    """
    Intenta obtener el número actual de participantes en la llamada de Google Meet.
    Retorna el número de personas detectado o -1 si no se pudo determinar.
    """
    try:
        participant_xpaths = [
            "//button[contains(@aria-label, 'personas') or contains(@aria-label, 'people') or contains(@aria-label, 'Mostrar a todos') or contains(@aria-label, 'Show everyone') or contains(@aria-label, 'participantes') or contains(@aria-label, 'participants')]",
            "//div[contains(@aria-label, 'personas') or contains(@aria-label, 'people') or contains(@aria-label, 'participantes') or contains(@aria-label, 'participants')]",
            "//div[contains(@class, 'uGfW4')]",
            "//button[@jsname='A533Id' or @jsname='r8qRAd']"
        ]

        for xpath in participant_xpaths:
            elements = driver.find_elements(By.XPATH, xpath)
            for elem in elements:
                aria = elem.get_attribute("aria-label") or ""
                text = elem.text or ""
                combined = f"{aria} {text}".lower()

                # Buscar patrones como "(1)", "1 persona", "1 participant", etc.
                match = re.search(r'\((\d+)\)', combined) or re.search(r'\b(\d+)\s*(personas|people|participantes|participants)\b', combined)
                if match:
                    count = int(match.group(1))
                    if 1 <= count <= 500:
                        return count

                # Si el texto directo del elemento es solo un número (ej. "1", "12")
                if text.strip().isdigit():
                    count = int(text.strip())
                    if 1 <= count <= 500:
                        return count

    except Exception:
        pass
    return -1


def is_in_active_call(driver: webdriver.Chrome) -> bool:
    """
    Verifica si el usuario está actualmente dentro de una llamada activa en Google Meet.
    """
    try:
        leave_btns = driver.find_elements(
            By.XPATH, 
            "//button[contains(@aria-label, 'Salir de la llamada') or contains(@aria-label, 'Leave call') or contains(@aria-label, 'Colgar') or @jsname='h1U9Be']"
        )
        return len(leave_btns) > 0 and any(btn.is_displayed() for btn in leave_btns)
    except Exception:
        return False


def check_meeting_ended(driver: webdriver.Chrome, elapsed_seconds: float = 0.0) -> bool:
    """
    Verifica si la llamada de Google Meet ha finalizado (porque el profesor cortó la llamada
    para todos, cerró la sala, se fueron los participantes o aparecieron modales de cierre).
    """
    try:
        url = driver.current_url.lower()
        # Redirecciones típicas tras salir o finalizar la llamada
        if "meet.google.com" in url and any(kw in url for kw in ["landing", "checkout", "ended", "byebye"]):
            logger.info("Detección de fin de llamada: Redireccionado a página de cierre.")
            return True

        # 1. Si ya pasó el tiempo inicial de ingreso (>15s) y el botón de colgar desapareció de la pantalla
        if elapsed_seconds > 15 and not is_in_active_call(driver):
            logger.info("Detección de fin de llamada: La reunión fue finalizada (el botón de salir ya no existe).")
            return True

        # 2. Escanear texto de la página y de posibles modales/diálogos emergentes
        page_text = driver.find_element(By.TAG_NAME, "body").text.lower()
        try:
            dialogs = driver.find_elements(By.XPATH, "//div[@role='dialog' or @role='alertdialog']")
            for dlg in dialogs:
                if dlg.is_displayed():
                    page_text += " " + dlg.text.lower()
        except Exception:
            pass

        # Mensajes explícitos de reunión finalizada
        ended_keywords = [
            "finalizado la llamada",
            "finalizó la llamada",
            "finalizó la reunión",
            "reunión finalizada",
            "llamada finalizada",
            "ha finalizado",
            "el anfitrión finalizó",
            "la llamada para todos",
            "has salido de la reunión",
            "te han eliminado",
            "has sido eliminado",
            "call has ended",
            "the call ended",
            "meeting ended",
            "you left the meeting",
            "you've been removed",
            "la llamada finalizó",
            "volver a la pantalla principal",
            "pantalla de inicio",
            "unirte de nuevo",
            "reintegrarse"
        ]

        for kw in ended_keywords:
            if kw in page_text:
                logger.info(f"Detección de fin de llamada: Detectado mensaje en pantalla/modal ('{kw}').")
                return True

        # 3. Mensajes o indicativos de "quedaste solo en la reunión"
        alone_keywords = [
            "solo tú",
            "solo tu",
            "solamente tú",
            "solamente tu",
            "eres el único",
            "eres la única",
            "no hay nadie más",
            "you're the only one",
            "you are the only one",
            "only person in the call",
            "you're the only person"
        ]

        for kw in alone_keywords:
            if kw in page_text:
                logger.info(f"Detección de fin de llamada: Quedaste solo en la reunión ('{kw}').")
                return True

        # 4. Conteo de participantes: si ha pasado un margen de estabilidad (>20s) y el conteo es <= 1
        if elapsed_seconds > 20:
            count = get_participant_count(driver)
            if count != -1 and count <= 1:
                logger.info(f"Detección de fin de llamada: Conteo de participantes = {count} (Quedaste solo en la reunión).")
                return True

    except Exception as e:
        logger.debug(f"Error en check_meeting_ended: {e}")

    return False


def monitor_attendance_loop(driver: webdriver.Chrome):
    """
    Loop principal de monitoreo pasivo y permanencia en la llamada.
    Fase 1: Detecta padrones enviados por otros usuarios y envía el propio cuando
            se alcanza el umbral de seguridad.
    Fase 2: Permanece en la clase de forma silenciosa hasta que la reunión finalice.
    """
    unique_detected_numbers: Set[str] = set()
    attendance_sent = False
    start_time = time.time()

    logger.info("=================================================================")
    logger.info(f"Iniciando monitoreo de chat. Esperando al menos {MIN_UNIQUE_NUMBERS} números distintos...")
    logger.info("=================================================================")

    while True:
        elapsed = time.time() - start_time
        if elapsed > MAX_MONITORING_TIME_SECONDS:
            logger.warning("Se alcanzó el tiempo máximo de monitoreo. Finalizando sesión.")
            break

        # 1. VERIFICAR PRIMERO SI LA LLAMADA O CLASE YA FINALIZÓ (ANTES DE INTENTAR ABRIR CHAT)
        if check_meeting_ended(driver, elapsed_seconds=elapsed):
            logger.info("=================================================================")
            if attendance_sent:
                logger.info("¡La clase ha finalizado! Asistencia registrada previamente con éxito.")
            else:
                logger.info("¡La clase ha finalizado! (No se solicitó o no se detectó toma de asistencia en esta clase).")
            logger.info("Desconectando y cerrando el bot...")
            logger.info("=================================================================")
            break

        # 2. FASE 1: Toma de Asistencia (Si aún no se envió)
        if not attendance_sent:
            # Asegurarse de que el chat siga abierto para leer mensajes
            ensure_chat_open(driver)

            # Escanear mensajes
            current_matches = scan_chat_for_numbers(driver)

            new_additions = False
            for num in current_matches:
                # Ignorar nuestro propio padrón si ya hubiese sido procesado
                if num != PADRON and num not in unique_detected_numbers:
                    unique_detected_numbers.add(num)
                    new_additions = True
                    logger.info(f"-> Nuevo padrón/DNI detectado en el chat: {num}")

            if new_additions:
                logger.info(
                    f"Estado actual de detección: {len(unique_detected_numbers)}/{MIN_UNIQUE_NUMBERS} números distintos "
                    f"| Detectados: {sorted(list(unique_detected_numbers))}"
                )

            # Verificación del umbral anti-falsos positivos
            if len(unique_detected_numbers) >= MIN_UNIQUE_NUMBERS:
                logger.info("=================================================================")
                logger.info(f"¡Toma de asistencia confirmada! ({len(unique_detected_numbers)} números detectados).")
                logger.info("=================================================================")
                
                # Enviar presente
                if send_attendance(driver, PADRON):
                    attendance_sent = True
                    logger.info("=================================================================")
                    logger.info("Presente enviado correctamente. El bot permanecerá en la llamada...")
                    logger.info("=================================================================")
        
        time.sleep(CHECK_INTERVAL_SECONDS)


def main():
    logger.info("=================================================================")
    logger.info("           INICIANDO MEET SHEEP BOT DE ASISTENCIA                ")
    logger.info("=================================================================")
    logger.info(f"Padrón configurado: {PADRON}")
    logger.info(f"Reunión: {MEET_URL}")
    if SCHEDULED_TIME:
        logger.info(f"Horario programado: {SCHEDULED_TIME} hs")
    logger.info(f"Perfil Chrome: {CHROME_USER_DATA_DIR} ({CHROME_PROFILE_DIRECTORY})")
    logger.info("=================================================================")

    if PADRON == "123456":
        logger.warning("RECUERDA: Estás usando el padrón por defecto ('123456'). Revisa la configuración si deseas cambiarlo.")

    # 0. Si hay una hora programada, esperar hasta que llegue dicha hora antes de abrir Chrome
    wait_for_scheduled_time(SCHEDULED_TIME)

    options = setup_chrome_options()
    driver = None

    try:
        # Inicialización del driver de Chrome utilizando webdriver_manager
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        
        # 1. Asegurar sesión activa de Google (pide login solo la primera vez)
        ensure_google_login(driver)

        # 2. Ingresar a la reunión
        if join_meet(driver):
            # 3. Asegurar que el chat esté abierto
            ensure_chat_open(driver)
            # 4. Monitorear el chat pasivamente
            monitor_attendance_loop(driver)
        else:
            logger.error("No se pudo completar el proceso de ingreso a la llamada.")

    except WebDriverException as e:
        logger.critical(f"Error en WebDriver de Selenium: {e}")
        if "user data directory is already in use" in str(e).lower():
            logger.error("¡ERROR CRÍTICO! Debes cerrar todas las ventanas abiertas de Google Chrome antes de ejecutar el bot con tu perfil local.")
    except KeyboardInterrupt:
        logger.info("Proceso interrumpido manualmente por el usuario.")
    except Exception as e:
        logger.critical(f"Ocurrió una excepción no esperada: {e}", exc_info=True)
    finally:
        if driver:
            logger.info("Cerrando el navegador...")
            try:
                driver.quit()
            except Exception:
                pass
            logger.info("Bot finalizado correctamente.")


if __name__ == "__main__":
    main()
