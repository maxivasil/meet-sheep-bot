# 🐑 Meet Sheep Bot - Bot de Asistencia Automática para Google Meet

Bot de automatización para **Google Meet** desarrollado en **Python** con **Selenium WebDriver**. 

Ingresa de forma silenciosa a tus clases de Google Meet, mantiene la cámara y micrófono desactivados, abre el panel de chat y monitorea los mensajes en segundo plano. Cuando detecta que otros alumnos están enviando sus números de padrón/DNI para la asistencia, el bot envía automáticamente tu número, guarda un registro con la marca de tiempo en `asistencia.log` y **permanece en la clase hasta que la reunión finalice** (detectando cuando el profesor corta la llamada o cuando se retiran los participantes).

---

## 🚀 Características Principales

- 🔐 **Uso de Perfil Local (Bypass de Login Google)**: Utiliza la carpeta `user-data-dir` de tu navegador Chrome para aprovechar tu sesión ya iniciada y evitar bloqueos o captchas de bots de Google.
- 🔇 **Ingreso Silencioso**: Pasa flags al navegador (`--use-fake-ui-for-media-stream`, `--mute-audio`) y atajos de teclado para asegurar que el micrófono y la cámara permanezcan bloqueados al ingresar.
- 💬 **Apertura Automática de Chat**: Detecta si el panel de chat está activo y lo abre si es necesario para cargar el DOM de mensajes.
- 🔍 **Detección por Regex**: Filtra patrones numéricos de 5 a 8 dígitos (DNIs o Padrones universitarios).
- 🛡️ **Lógica Anti-Falsos Positivos**: Cuenta números distintos enviados por otros usuarios antes de proceder. Requiere al menos 5 padrones únicos (configurables) para confirmar que la cátedra está tomando lista.
- ⏳ **Permanencia y Detección de Fin de Clase**: Permanece en la videollamada tras enviar el presente y se desconecta de forma limpia cuando el profesor finaliza la reunión o cuando te quedas solo en la sala.
- 📝 **Log con timestamp**: Registra en un archivo `asistencia.log` la hora exacta en la que diste el presente y el evento de cierre de la clase.

---

## 🛠️ Requisitos Previos e Instalación

1. **Python 3.8+** instalado en tu sistema.
2. **Google Chrome** instalado.

### 1. Crear entorno virtual e instalar dependencias

Ya he creado el entorno virtual `venv` e instalado las librerías necesarias. Si necesitas crearlo o reinstalarlo manualmente:

```bash
cd meet-sheep-bot

# Crear entorno virtual y activar
python3 -m venv venv
source venv/bin/activate

# Instalar dependencias
pip install -r requirements.txt
```

---

## ⚙️ Configuración

Puedes configurar el bot editando directamente las variables en la sección de configuración de `meet_bot.py` o mediante un archivo `.env`.

### 1. Configuración directas en `meet_bot.py`

Abre `meet_bot.py` y modifica las siguientes variables en la parte superior:

```python
# 1. Tu número de padrón o DNI
PADRON = "12345678"  # <--- Coloca tu número de padrón aquí

# 2. URL del Meet de la clase
MEET_URL = "https://meet.google.com/abc-defg-hij"  # <--- URL del Meet

# 3. Hora programada de inicio (Opcional, ej: "06:30"). Si está vacío "", se ejecuta inmediatamente.
SCHEDULED_TIME = "06:30"

# 4. Ruta a la carpeta User Data de Chrome (Opcional, autodetectada si se deja vacío)
CHROME_USER_DATA_DIR = ""

# 5. Perfil de Chrome ("Default", "Profile 1", "Profile 2", etc.)
CHROME_PROFILE_DIRECTORY = "Default"

# 6. Nombre de usuario a completar si Google Meet lo solicita
DISPLAY_NAME = "Estudiante"
```

### 2. Configuración mediante `.env` (Recomendado)

Copia `.env.example` a `.env` y completa tus datos:

```env
MEET_PADRON=12345678
MEET_URL=https://meet.google.com/abc-defg-hij
MEET_SCHEDULED_TIME=06:30
MEET_DISPLAY_NAME=Estudiante
CHROME_USER_DATA_DIR=
CHROME_PROFILE_DIRECTORY=Default
```

---

## ⚠️ Nota Importante sobre el Perfil de Chrome

> **¡IMPORTANTE!** Google Chrome no permite que dos procesos independientes utilicen el mismo `user-data-dir` simultáneamente.  
> **Antes de ejecutar el script, debes cerrar todas las ventanas abiertas de Chrome** en tu equipo, o de lo contrario Selenium arrojará un error de *"user data directory is already in use"*.

---

## 🏃 Ejecución

Para iniciar el bot:

```bash
# Opción 1: Usando el python del entorno virtual directamente
./venv/bin/python3 meet_bot.py

# Opción 2: Activando el entorno virtual previamente
source venv/bin/activate
python3 meet_bot.py
```

### Flujo de Ejecución:

1. Inicia Chrome con tus credenciales y flags silenciosas.
2. Ingresa a la URL del Meet y presiona automáticamente en **"Unirse ahora"**.
3. Silencia cámara y micrófono.
4. Abre el panel de chat en la barra lateral.
5. Monitorea los mensajes cada 3 segundos.
6. Al detectar al menos **5 padrones distintos** enviados por otros usuarios, escribe tu padrón, presiona **Enter** y guarda la hora en `asistencia.log`.
7. Permanece en la videollamada en segundo plano y se desconecta automáticamente cuando el profesor finaliza la reunión o cuando la sala queda vacía.

---

## 📄 Archivo de Registro (`asistencia.log`)

El script registrará la salida en consola y creará un archivo `asistencia.log` con el historial de eventos:

```text
[2026-08-30 18:30:15] [INFO] Navegando a la reunión: https://meet.google.com/abc-defg-hij
[2026-08-30 18:30:20] [INFO] Click realizado en el botón de unirse a la llamada.
[2026-08-30 18:30:23] [INFO] El panel de chat ya está abierto y visible.
[2026-08-30 18:35:10] [INFO] -> Nuevo padrón/DNI detectado en el chat: 98123
[2026-08-30 18:35:13] [INFO] -> Nuevo padrón/DNI detectado en el chat: 104521
[2026-08-30 18:35:16] [INFO] -> Nuevo padrón/DNI detectado en el chat: 88741
[2026-08-30 18:35:16] [INFO] ¡Toma de asistencia confirmada! (5 números detectados).
[2026-08-30 18:35:17] [INFO] === PRESENTE ENVIADO CON ÉXITO === | Padrón: 109876 | Hora: 2026-08-30 18:35:17
[2026-08-30 18:35:17] [INFO] Presente enviado correctamente. El bot permanecerá en la llamada...
[2026-08-30 20:15:00] [INFO] Detección de fin de llamada: Quedaste solo en la reunión.
[2026-08-30 20:15:00] [INFO] ¡La clase ha finalizado! Desconectando y cerrando el bot...
```

---

## 🛡️ Licencia
MIT