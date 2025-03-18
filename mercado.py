# mercado.py - Versión corregida
from flask import Flask, render_template, request, redirect, url_for, jsonify, flash, session, Response
import asyncio
import ccxt.async_support as ccxt_async
import time
import logging
import json
import os
import sys
from functools import wraps
import threading
import bot  # Importamos el bot principal para usar sus credenciales y funciones
import app as main_app


# Configuración de logging
logging.basicConfig(
    level=logging.ERROR,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("mercado.log"),
        logging.StreamHandler()
    ]
)

app = Flask(__name__)
app.secret_key = 'tu_clave_secreta_aqui'
app.secret_key = main_app.app.secret_key

# Añade esta línea
app.config['APPLICATION_ROOT'] = '/mercado'

# Declarar el loop como variable global
loop = None


# Directorio para configuración del mercado
config_directory = 'mercado_config'
if not os.path.exists(config_directory):
    os.makedirs(config_directory)

# Estructura para seguimiento de acceso a datos
market_user_data_access = {}  # {user_id: last_access_timestamp}

# Modificar la función login_required para compartir sesión
def shared_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' in session:
            # Si existe user_id en la sesión compartida, está autenticado
            return f(*args, **kwargs)
        else:
            # Redirigir a la página principal en lugar de login
            return redirect(url_for('index'))
    return decorated_function

# Reemplazar la versión original de login_required
login_required = shared_login_required


# Función para cargar configuración de mercado
def load_market_config(user_id):
    config_file = os.path.join(config_directory, f'market_config_{user_id}.json')

    if os.path.exists(config_file):
        try:
            with open(config_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Error al cargar la configuración de mercado para {user_id}: {str(e)}")

    return {}


# Función para guardar configuración de mercado
def save_market_config(user_id, config):
    config_file = os.path.join(config_directory, f'market_config_{user_id}.json')

    try:
        with open(config_file, 'w') as f:
            json.dump(config, f, indent=4)
        return True
    except Exception as e:
        logging.error(f"Error al guardar la configuración de mercado para {user_id}: {str(e)}")
        return False

# Función para registrar actividad de usuario
def mark_market_user_active(user_id):
    market_user_data_access[user_id] = time.time()

# Asegúrate de que bot ya haya sido importado y que exista load_encrypted_config en bot.py

# Semáforos específicos por usuario y exchange para mercado
market_rate_limiters = {}


# Función para liberar memoria de usuarios inactivos en mercado
async def market_memory_optimizer():
    while True:
        current_time = time.time()
        inactive_threshold = 3600  # 1 hora de inactividad

        for user_id, last_access in list(market_user_data_access.items()):
            if current_time - last_access > inactive_threshold:
                await offload_market_user_data(user_id)

        await asyncio.sleep(300)  # Verificar cada 5 minutos


# Función para descargar datos de usuario de mercado a disco
async def offload_market_user_data(user_id):
    try:
        # Guardar configuración de mercado
        config = load_market_config(user_id)
        if config:
            save_market_config(user_id, config)

        # Limpiar los semáforos si existen
        if user_id in market_rate_limiters:
            del market_rate_limiters[user_id]

        logging.info(f"Datos de mercado del usuario {user_id} descargados a disco por inactividad")
    except Exception as e:
        logging.error(f"Error al descargar datos de mercado del usuario {user_id}: {e}")

def get_market_rate_limiter(user_id, exchange_id):
    if user_id not in market_rate_limiters:
        market_rate_limiters[user_id] = {}
    if exchange_id not in market_rate_limiters[user_id]:
        # Crear un semáforo específico para este usuario/exchange
        market_rate_limiters[user_id][exchange_id] = asyncio.Semaphore(3)
    return market_rate_limiters[user_id][exchange_id]


async def initialize_exchange(user_id, exchange_id):
    try:
        # Marcar al usuario como activo
        mark_market_user_active(user_id)

        # Si aún no se cargó la configuración del usuario, cárgala
        if user_id not in bot.users_exchanges_config:
            bot.load_encrypted_config(user_id)
        exchange_config = bot.users_exchanges_config[user_id][exchange_id]
        exchange_class = getattr(ccxt_async, exchange_config['name'])
        exchange_params = {
            'apiKey': exchange_config['api_key'],
            'secret': exchange_config['secret'],
            'enableRateLimit': True
        }
        if 'password' in exchange_config and exchange_config['password']:
            exchange_params['password'] = exchange_config['password']
        if user_id not in bot.users_exchanges:
            bot.users_exchanges[user_id] = {}

        # Usar rate limiter específico
        rate_limiter = get_market_rate_limiter(user_id, exchange_id)
        async with rate_limiter:
            bot.users_exchanges[user_id][exchange_id] = exchange_class(exchange_params)
            # Cargar mercados de forma forzada
            init_coro = bot.users_exchanges[user_id][exchange_id].load_markets()
            future = asyncio.run_coroutine_threadsafe(init_coro, bot.loop)
            future.result(timeout=30)

        logging.info(f"Exchange {exchange_id} inicializado exitosamente para el usuario {user_id}")
    except Exception as e:
        logging.error(f"Error al inicializar el exchange {exchange_id} para {user_id}: {str(e)}")


async def get_tickers(user_id, exchange_id, symbols=None):
    try:
        # Marcar al usuario como activo
        mark_market_user_active(user_id)

        # Cargar configuración si no está cargada
        if user_id not in bot.users_exchanges_config:
            bot.load_encrypted_config(user_id)

        # Inicializar exchange si aún no existe
        if user_id not in bot.users_exchanges or exchange_id not in bot.users_exchanges[user_id]:
            await initialize_exchange(user_id, exchange_id)

        exchange = bot.users_exchanges[user_id][exchange_id]

        if not symbols or (isinstance(symbols, list) and not symbols[0]):
            logging.warning(f"Lista de símbolos vacía para {exchange_id}.")
            return {}

        # Log de los símbolos que se van a recuperar
        logging.info(f"Recuperando tickers para {exchange_id}: {symbols}")

        try:
            # Usar rate limiter específico
            rate_limiter = get_market_rate_limiter(user_id, exchange_id)
            async with rate_limiter:
                tickers = await exchange.fetch_tickers(symbols)

            logging.info(f"Tickers recuperados para {exchange_id}: {list(tickers.keys())}")
        except Exception as e:
            logging.error(f"Error al obtener tickers para {exchange_id}: {e}")
            return {}

        price_data = {}
        for symbol, ticker in tickers.items():
            if ticker:
                price_data[symbol] = {
                    'price': ticker.get('last', 0),
                    'change24h': ticker.get('percentage', 0),
                    'volume24h': ticker.get('quoteVolume', 0),
                    'high24h': ticker.get('high', 0),
                    'low24h': ticker.get('low', 0),
                    'bid': ticker.get('bid', 0),
                    'ask': ticker.get('ask', 0),
                    'timestamp': ticker.get('timestamp', 0)
                }

        return price_data
    except Exception as e:
        logging.error(f"Error general en get_tickers para {exchange_id} del usuario {user_id}: {e}")
        return {}
@app.route('/api/price-stream/<exchange_id>')
@login_required
def price_stream(exchange_id):
    # Extraer el user_id (según se usa en app.py y bot.py)
    user_id_local = session.get('user_id')
    if not user_id_local:
        user_id_local = request.args.get('user_id')
    if not user_id_local:
        return Response("data: " + json.dumps({'error': 'No user ID found'}) + "\n\n", mimetype="text/event-stream")

    # Extraer y procesar tokens fuera del generador
    tokens_param = request.args.get('tokens', '')
    selected_tokens = tokens_param.split(',') if tokens_param else []
    selected_tokens = [token for token in selected_tokens if token]

    logging.info(f"Procesando tokens para {exchange_id}: {selected_tokens}")

    if not selected_tokens:
        return Response("data: {}\n\n", mimetype="text/event-stream")

    def generate(user_id, tokens):
        while True:
            try:
                # Usar run_coroutine_threadsafe en lugar de asyncio.run
                future = asyncio.run_coroutine_threadsafe(
                    get_tickers(user_id, exchange_id, tokens),
                    loop  # Usar el loop global
                )
                price_data = future.result(timeout=5)  # Agregar timeout para evitar bloqueos

                if price_data:
                    logging.info(f"Datos obtenidos: {len(price_data)} tokens")
                    data_str = json.dumps(price_data)
                    logging.info(f"Enviando datos al cliente: {data_str[:100]}...")  # Log primeros 100 caracteres
                    yield f"data: {data_str}\n\n"
                else:
                    logging.warning(f"No hay datos para enviar en {exchange_id}")
                    yield "data: {}\n\n"
                time.sleep(1)
            except Exception as e:
                logging.error(f"Stream error: {str(e)}")
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
                time.sleep(5)

    return Response(generate(user_id_local, selected_tokens), mimetype="text/event-stream")

# Rutas de la aplicación
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('mercado'))
    else:
        return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user_id = request.form.get('username')
        password = request.form.get('password')

        # Usar la función de autenticación del bot principal
        if bot.authenticate_user(user_id, password):
            session['user_id'] = user_id
            flash(f"Bienvenido, {user_id}!", "success")
            return redirect(url_for('mercado'))
        else:
            flash("Credenciales incorrectas.", "error")

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash("Sesión cerrada exitosamente.", "success")
    return redirect(url_for('login'))


@app.route('/mercado')
@login_required
def mercado():
    user_id = session.get('user_id')

    # Marcar al usuario como activo
    mark_market_user_active(user_id)

    # Obtener configs del bot principal
    exchanges_config = bot.users_exchanges_config.get(user_id, {})

    status = {
        exchange_id: bot.users_exchange_running_status[user_id].get(exchange_id, False)
        for exchange_id in exchanges_config.keys()
    }

    return render_template(
        'mercado.html',
        exchanges_config=exchanges_config,
        status=status,
        user_id=user_id
    )


@app.route('/api/available-tokens')
@login_required
def available_tokens_api():
    user_id = session.get('user_id')

    # Marcar al usuario como activo
    mark_market_user_active(user_id)

    # Inicializar diccionario de tokens disponibles
    tokens_dict = {}

    # Asegurarse que el usuario exista en las estructuras del bot
    if user_id not in bot.users_exchanges_config:
        bot.load_encrypted_config(user_id)
        bot.initialize_structures(user_id)

    # Intentar inicializar TODOS los exchanges del usuario si no están conectados
    for exchange_id, exchange_config in bot.users_exchanges_config[user_id].items():
        if exchange_config.get('active', False):
            if exchange_id not in bot.users_exchanges.get(user_id, {}):
                try:
                    # Crear y configurar el objeto de exchange usando las credenciales del usuario
                    exchange_class = getattr(ccxt_async, exchange_config['name'])
                    exchange_params = {
                        'apiKey': exchange_config['api_key'],
                        'secret': exchange_config['secret'],
                        'enableRateLimit': True
                    }
                    if 'password' in exchange_config and exchange_config['password']:
                        exchange_params['password'] = exchange_config['password']

                    # Inicializar el exchange
                    if user_id not in bot.users_exchanges:
                        bot.users_exchanges[user_id] = {}

                    bot.users_exchanges[user_id][exchange_id] = exchange_class(exchange_params)

                    # Cargar los mercados de manera forzada
                    init_coro = bot.users_exchanges[user_id][exchange_id].load_markets()
                    future = asyncio.run_coroutine_threadsafe(init_coro, bot.loop)
                    future.result(timeout=30)  # Tiempo extendido para mercados grandes

                    logging.info(f"Exchange {exchange_id} inicializado exitosamente para el usuario {user_id}")
                except Exception as e:
                    logging.error(f"Error al inicializar el exchange {exchange_id}: {str(e)}")
                    continue

    # Recorrer los exchanges inicializados para obtener todos los tokens
    for exchange_id, exchange in bot.users_exchanges.get(user_id, {}).items():
        try:
            if not hasattr(exchange, 'markets') or not exchange.markets:
                try:
                    # Forzar carga de mercados si no están disponibles
                    load_markets_coro = exchange.load_markets()
                    future = asyncio.run_coroutine_threadsafe(load_markets_coro, bot.loop)
                    future.result(timeout=30)
                except Exception as e:
                    logging.error(f"Error al cargar mercados para {exchange_id}: {str(e)}")
                    tokens_dict[exchange_id] = {}
                    continue

            # Extraer TODOS los pares de trading disponibles
            exchange_tokens = {}
            for symbol, market in exchange.markets.items():
                # Incluir todos los mercados activos independientemente del tipo
                if market.get('active', False):
                    exchange_tokens[symbol] = {
                        'name': market.get('name', symbol),
                        'base': market.get('base', ''),
                        'quote': market.get('quote', '')
                    }

            tokens_dict[exchange_id] = exchange_tokens
            logging.info(f"Obtenidos {len(exchange_tokens)} tokens para {exchange_id}")

        except Exception as e:
            logging.error(f"Error al procesar tokens para {exchange_id}: {str(e)}")
            tokens_dict[exchange_id] = {}

    if not tokens_dict:
        logging.warning(f"No se encontraron tokens para ningún exchange del usuario {user_id}")

    return jsonify(tokens_dict)


@app.route('/api/market-config', methods=['GET', 'POST'])
@login_required
def market_config_api():
    user_id = session.get('user_id')

    # Marcar al usuario como activo
    mark_market_user_active(user_id)

    if request.method == 'POST':
        try:
            config = request.json
            success = save_market_config(user_id, config)
            if success:
                return jsonify({"success": True, "message": "Configuración guardada correctamente."})
            else:
                return jsonify({"success": False, "message": "Error al guardar la configuración."})
        except Exception as e:
            return jsonify({"success": False, "message": f"Error: {str(e)}"})
    else:
        # GET: Retornar configuración actual
        return jsonify(load_market_config(user_id))


@app.route('/api/account-balance/<exchange_id>')
@login_required
def account_balance_api(exchange_id):
    user_id = session.get('user_id')

    # Marcar al usuario como activo
    mark_market_user_active(user_id)

    try:
        # Verificar que el exchange existe y está inicializado
        if user_id not in bot.users_exchanges or exchange_id not in bot.users_exchanges[user_id]:
            # Inicializar el exchange
            init_coro = initialize_exchange(user_id, exchange_id)
            future = asyncio.run_coroutine_threadsafe(init_coro, bot.loop)
            future.result(timeout=10)

        exchange = bot.users_exchanges[user_id][exchange_id]

        # Agregar manejo de errores más específico
        try:
            # Obtener el balance de la cuenta
            balance_coro = exchange.fetch_balance()
            future = asyncio.run_coroutine_threadsafe(balance_coro, bot.loop)
            balance = future.result(timeout=10)

            # Verificar si balance es None o no tiene el formato esperado
            if not balance or not isinstance(balance, dict):
                return jsonify({
                    'error': f"Formato de respuesta de balance inválido",
                    'total_balance': 0,
                    'balances': []
                })

            # Obtener precios actuales para calcular valores
            try:
                tickers_coro = exchange.fetch_tickers()
                future = asyncio.run_coroutine_threadsafe(tickers_coro, bot.loop)
                tickers = future.result(timeout=10)
            except Exception as ticker_error:
                # Si falla la obtención de tickers, continuamos con un diccionario vacío
                tickers = {}
                logging.warning(f"No se pudieron obtener tickers para {exchange_id}: {str(ticker_error)}")

            # Procesar el balance para el formato requerido
            processed_balance = []
            total_balance_value = 0

            # Verificar si 'total' existe en balance
            if 'total' in balance:
                balance_items = balance['total'].items()
            else:
                # Iterar sobre todas las claves en balance (podría variar según el exchange)
                balance_items = []
                for currency, amounts in balance.items():
                    # Excluir claves que no son monedas
                    if currency not in ['info', 'timestamp', 'datetime', 'free', 'used', 'total']:
                        # Verificar si amounts es dict y tiene 'total'
                        if isinstance(amounts, dict) and 'total' in amounts:
                            balance_items.append((currency, amounts))

            for currency, amounts in balance_items:
                # Obtener valores, con comprobación de tipos
                total_amount = 0
                available = 0
                in_order = 0

                if isinstance(amounts, dict):
                    total_amount = float(amounts.get('total', 0) or 0)
                    available = float(amounts.get('free', 0) or 0)
                    in_order = float(amounts.get('used', 0) or 0)
                elif isinstance(amounts, (int, float)):
                    total_amount = float(amounts)

                # Excluir monedas con saldo cero
                if total_amount <= 0:
                    continue

                # Determinar el precio en USDT
                price = 1.0  # Valor por defecto para USDT
                if currency == 'USDT':
                    price = 1.0
                else:
                    # Buscar pares con USDT
                    symbol = f'{currency}/USDT'
                    if symbol in tickers and 'last' in tickers[symbol]:
                        price = tickers[symbol]['last']
                    else:
                        # Si no encontramos el precio, usamos 0 pero seguimos mostrando el token
                        price = 0

                # Calcular valor total
                total_value = total_amount * price
                total_balance_value += total_value

                processed_balance.append({
                    'asset': currency,
                    'available': available,
                    'in_order': in_order,
                    'price': price,
                    'total_value': total_value
                })

            # Ordenar por valor total, de mayor a menor
            processed_balance.sort(key=lambda x: x['total_value'], reverse=True)

            return jsonify({
                'total_balance': total_balance_value,
                'balances': processed_balance
            })

        except Exception as balance_error:
            logging.error(f"Error específico al obtener balance para {exchange_id}: {str(balance_error)}")
            return jsonify({
                'error': f"Error al obtener balance: {str(balance_error)}",
                'total_balance': 0,
                'balances': []
            })

    except Exception as e:
        logging.error(f"Error general al obtener balance para {exchange_id}: {str(e)}")
        return jsonify({
            'error': f"Error al obtener balance: {str(e)}",
            'total_balance': 0,
            'balances': []
        })

# Función para ejecutar Flask
def run_flask():
    app.run(host='0.0.0.0', port=5003, debug=False, use_reloader=False)


# Función principal
if __name__ == '__main__':
    # Inicializar el loop global
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Compartir el loop con el bot
    bot.loop = loop

    # Iniciar el optimizador de memoria
    asyncio.run_coroutine_threadsafe(market_memory_optimizer(), loop)

    # Iniciar Flask en un hilo separado
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    try:
        # Ejecutar el loop de eventos
        loop.run_forever()
    except KeyboardInterrupt:
        logging.info("Cierre de la aplicación por el usuario")
    finally:
        loop.close()