# main.py (corregido para Windows)
from flask import Flask, session
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.serving import run_simple
import asyncio
import logging
import os
import sys
import threading
import platform  # Añadimos esto para detectar el sistema operativo
from functools import wraps

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("main_combined.log"),
        logging.StreamHandler()
    ]
)

# Asegurarse de que exista el directorio static
if not os.path.exists('static'):
    os.makedirs('static')
    # Crear un CSS básico
    with open('static/styles.css', 'w') as f:
        f.write("""
        body { font-family: Arial, sans-serif; margin: 20px; }
        .container { max-width: 1200px; margin: 0 auto; }
        """)

# CORRECCIÓN PRINCIPAL: Usar SelectorEventLoop en Windows
if platform.system() == 'Windows':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    logging.info("Configurado WindowsSelectorEventLoopPolicy para compatibilidad en Windows")

# Crear un nuevo loop de eventos asíncrono
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

# Añadir directorio actual al path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

# Importar los módulos después de configurar el loop
import bot
import app
import mercado

# Asignar el loop a todos los módulos
bot.loop = loop
app.loop = loop
mercado.loop = loop

# Compartir secret_key
mercado.app.secret_key = app.app.secret_key

# Configurar prefijo para mercado
mercado.app.config['APPLICATION_ROOT'] = '/mercado'

# Modificar función login_required para mercado
def shared_login_required(f):
    @wraps(f)
    def wrap(*args, **kwargs):
        if 'user_id' in session:
            return f(*args, **kwargs)
        else:
            from flask import redirect, flash, url_for
            flash("Por favor, inicie sesión para acceder a esta página.", "error")
            return redirect(url_for('login'))
    return wrap

# Aplicar la función compartida
mercado.login_required = shared_login_required

# Configurar carpetas de plantillas y estáticos correctamente
mercado.app.template_folder = os.path.join(current_dir, 'templates')
mercado.app.static_folder = os.path.join(current_dir, 'static')
app.app.template_folder = os.path.join(current_dir, 'templates')
app.app.static_folder = os.path.join(current_dir, 'static')

# Función para ejecutar el servidor combinado
def run_combined_app():
    application = DispatcherMiddleware(
        app.app,
        {
            '/mercado': mercado.app
        }
    )
    run_simple('0.0.0.0', 5003, application,
               use_reloader=False,
               threaded=True,
               use_debugger=False)

# Cargar usuarios al iniciar
bot.load_users()

# Iniciar optimizadores de memoria de forma segura
try:
    asyncio.run_coroutine_threadsafe(bot.memory_optimizer(), loop)
    logging.info("Optimizador de memoria de bot iniciado correctamente")
except Exception as e:
    logging.error(f"Error al iniciar el optimizador de memoria de bot: {e}")

try:
    if hasattr(mercado, 'market_memory_optimizer'):
        asyncio.run_coroutine_threadsafe(mercado.market_memory_optimizer(), loop)
        logging.info("Optimizador de memoria de mercado iniciado")
except Exception as e:
    logging.error(f"Error al iniciar el optimizador de memoria de mercado: {e}")

if __name__ == '__main__':
    # Configurar límites de usuario de forma segura
    for user_id in bot.users:
        try:
            if hasattr(bot, 'configure_user_limits') and user_id in bot.users_exchanges_config:
                bot.configure_user_limits(user_id)
        except Exception as e:
            logging.error(f"Error al configurar límites para el usuario {user_id}: {e}")

    # Iniciar servidor en hilo separado
    server_thread = threading.Thread(target=run_combined_app)
    server_thread.daemon = True
    server_thread.start()

    logging.info("Servidor web iniciado en el puerto 5003")
    logging.info("Accede a la aplicación principal en http://localhost:5003")
    logging.info("Accede a mercado en http://localhost:5003/mercado")

    try:
        # Ejecutar loop de eventos
        loop.run_forever()
    except KeyboardInterrupt:
        logging.info("Cierre de la aplicación por el usuario")
    except Exception as e:
        logging.error(f"Error en la ejecución: {e}")
    finally:
        # Cerrar recursos de forma segura
        for user_id in list(bot.users.keys()):
            try:
                if user_id in bot.users_exchanges:
                    loop.run_until_complete(bot.shutdown_bot(user_id))
            except Exception as e:
                logging.error(f"Error al cerrar sesión de usuario {user_id}: {e}")
        loop.close()
        logging.info("Aplicación cerrada correctamente")