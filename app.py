from flask import Flask, render_template, request, redirect, url_for, jsonify, flash, session
import asyncio
import bot  # Asegúrate de que bot.py esté en el mismo directorio
import threading
import logging
import os
import json
import time
import re
import uuid
import hashlib
from urllib.parse import unquote
from concurrent.futures import ThreadPoolExecutor
from functools import wraps  # Importamos wraps desde functools
from bot import load_transactions
from bot import save_transaction, calculate_pnl, load_transactions, get_total_pnl, show_pnl, save_trade, load_trades
import random
from flask import Response
from datetime import datetime, timedelta


app = Flask(__name__)
app.secret_key = 'tu_clave_secreta_aqui'  # Reemplaza con una clave secreta segura

# Configuración de logging
logging.basicConfig(
    level=logging.ERROR,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)

# Crear un nuevo bucle de eventos
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

# Asignar el loop al bot
bot.loop = loop
bot.load_users()

def login_required(f):
    @wraps(f)
    def wrap(*args, **kwargs):
        if 'user_id' not in session:
            flash("Por favor, inicie sesión para acceder a esta página.", "error")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrap


@app.route('/')
@login_required
def index():
    user_id = session.get('user_id')
    if not user_id:
        flash("Por favor, inicie sesión para acceder a esta página.", "error")
        return redirect(url_for('login'))

    # Marcar al usuario como activo
    bot.mark_user_active(user_id)

    if user_id not in bot.users_exchanges_config:
        bot.load_encrypted_config(user_id)
        bot.initialize_structures(user_id)

    status = {
        exchange_id: bot.users_exchange_running_status[user_id].get(exchange_id, False)
        for exchange_id in bot.users_exchanges_config[user_id].keys()
    }

    exchanges_config = bot.users_exchanges_config.get(user_id, {})
    order_tracker = bot.users_order_trackers.get(user_id)

    if order_tracker is None:
        bot.initialize_structures(user_id)
        order_tracker = bot.users_order_trackers[user_id]

    symbols_config = bot.users_symbols_config.get(user_id, [])

    bot_status = bot.users_bot_status.get(user_id, False)

    dashboard_data = get_dashboard_data(user_id)
    return render_template(
        'index.html',
        status=status,
        exchanges_config=exchanges_config,
        order_tracker=order_tracker,
        symbols_config=symbols_config,
        user_id=user_id,
        bot=bot,
        bot_status=bot_status,
        infinity_stats=dashboard_data['infinity_stats']
    )

@app.route('/clear_pending_sell_orders', methods=['POST'])
@login_required
def clear_pending_sell_orders_route():
    user_id = session['user_id']
    exchange_id = request.form.get('exchange_id')
    symbol = request.form.get('symbol')
    if not exchange_id or not symbol:
        return jsonify({"success": False, "message": "Exchange y símbolo son requeridos."})
    try:
        coro = bot.clear_pending_sell_orders(user_id, exchange_id, symbol)
        future = asyncio.run_coroutine_threadsafe(coro, bot.loop)
        future.result(timeout=10)
        return jsonify({"success": True, "message": "Órdenes pendientes de venta eliminadas correctamente."})
    except Exception as e:
        return jsonify({"success": False, "message": f"Error al eliminar órdenes pendientes de venta: {str(e)}"})


def get_dashboard_data(user_id):
    infinity_stats = []
    # Obtener estadísticas de Infinity para todos los tokens
    try:
        for exchange_id, exchange in bot.users_exchanges_config[user_id].items():
            for token in bot.users_symbols_config[user_id]:
                if token.get('strategy') == 'infinity' and exchange_id in token.get('exchanges', []):
                    try:
                        # Determinar si el token está activo
                        token_activo = False
                        if (user_id in bot.users_token_running_status and
                                exchange_id in bot.users_token_running_status[user_id] and
                                token['symbol'] in bot.users_token_running_status[user_id][exchange_id]):
                            token_activo = bot.users_token_running_status[user_id][exchange_id][token['symbol']]

                        # Datos base
                        active_orders = {'buy': 0, 'sell': 0}

                        # Obtener PnL directamente
                        pnl = bot.users_profit_loss.get(user_id, {}).get(exchange_id, {}).get(token['symbol'], 0)

                        # Obtener datos de reinversión
                        reinversion_percentage = float(token.get('reinvestment_percentage', 75.0))
                        capital_total = float(token.get('total_balance_usdt', 0))

                        # Calcular ganancias reinvertidas totales
                        ganancias_reinvertidas = bot.users_reinvested_profits.get(user_id, {}).get(exchange_id, {}).get(
                            token['symbol'], 0)

                        # Calcular ROI
                        roi = bot.get_infinity_roi(user_id, exchange_id, token['symbol'])

                        # Solo intentar obtener datos activos si el token está corriendo
                        if token_activo:
                            try:
                                # Usar un timeout corto para evitar bloqueos
                                active_orders = bot.get_infinity_active_orders(user_id, exchange_id, token['symbol'])
                            except Exception as e:
                                logging.error(f"Error obteniendo datos activos: {e}")

                        infinity_stats.append({
                            'exchange_id': exchange_id,
                            'symbol': token['symbol'],
                            'pnl': pnl,
                            'capital_total': capital_total,
                            'ganancias_reinvertidas': ganancias_reinvertidas,
                            'ordenes_compra': active_orders.get('buy', 0),
                            'ordenes_venta': active_orders.get('sell', 0),
                            'activo': token_activo,
                            'roi': roi
                        })
                    except Exception as e:
                        logging.error(f"Error al procesar token {token['symbol']} en {exchange_id}: {e}")
                        # Continuar con el siguiente token en caso de error
    except Exception as e:
        logging.error(f"Error general en get_dashboard_data: {e}")
        # No bloqueamos la función aunque haya errores

    # Asegurar que siempre devolvemos un diccionario válido
    return {
        'exchanges_config': bot.get_exchanges_config(user_id),
        'status': bot.get_exchange_statuses(user_id),
        'pnl': bot.get_all_pnl(user_id),
        'infinity_stats': infinity_stats
    }

@app.route('/stream/<user_id>')
def stream(user_id):
    def event_stream():
        while True:
            try:
                data = get_dashboard_data(user_id)
                yield f"data: {json.dumps(data)}\n\n"
            except Exception as e:
                logging.error(f"Error en stream para {user_id}: {e}")
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
            time.sleep(15)
    return Response(event_stream(), mimetype="text/event-stream")

@app.route('/logout')
def logout():
    user_id = session.get('user_id')
    bot_running = any(bot.users_exchange_running_status.get(user_id, {}).values())
    if bot_running:
        return jsonify(
            {"confirm_logout": True, "message": "El bot está en ejecución. ¿Desea detenerlo antes de cerrar sesión?"})
    else:
        session.pop('user_id', None)
        flash("Sesión cerrada exitosamente.", "success")
        return jsonify({"redirect": url_for('login')})

@app.route('/confirm_logout', methods=['POST'])
def confirm_logout():
    user_id = session.get('user_id')
    stop_bot = request.json.get('stop_bot', False)

    if stop_bot:
        for exchange_id in bot.users_exchange_running_status.get(user_id, {}):
            asyncio.run_coroutine_threadsafe(bot.stop_exchange_task_async(user_id, exchange_id), bot.loop)
        bot.users_bot_status[user_id] = False
    else:
        bot.users_bot_status[user_id] = True

    session.pop('user_id', None)
    flash("Sesión cerrada exitosamente.", "success")
    return jsonify({"redirect": url_for('login')})

@app.route('/save_transaction', methods=['POST'])
@login_required
def save_transaction_route():
    user_id = session['user_id']
    data = request.json
    bot.save_transaction(user_id, data['exchange_id'], data['symbol'], data['buy_order'], data['sell_order'], data['commission'])
    return jsonify({"success": True})

@app.route('/show_pnl/<exchange_id>')
@login_required
def show_pnl_route(exchange_id):
    user_id = session['user_id']
    pnl_data = bot.show_pnl(user_id, exchange_id)  # Ya no será None
    return jsonify(pnl_data)

@app.route('/tutorial')
def tutorial():
    return render_template('tutorial.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        user_id = request.form.get('username')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        email = request.form.get('email')

        if password != confirm_password:
            flash("Las contraseñas no coinciden.", "error")
            return redirect(url_for('register'))

        security_questions = [
            {
                'question': request.form.get(f'question_{i}'),
                'answer': hashlib.sha256(request.form.get(f'answer_{i}').encode()).hexdigest()
            }
            for i in range(1, 3)
        ]

        success, message = bot.register_user(user_id, password, email, security_questions)
        if success:
            flash(message, "success")
            return redirect(url_for('login'))
        else:
            flash(message, "error")

    return render_template('register.html', questions=bot.security_questions)

@app.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    user_id = session['user_id']
    is_reset = 'reset_user_id' in session

    if request.method == 'POST':
        old_password = request.form.get('old_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        email = request.form.get('email')

        if new_password != confirm_password:
            flash("Las nuevas contraseñas no coinciden.", "error")
        else:
            if is_reset:
                success, message = bot.reset_password(user_id, new_password, email)
            else:
                success, message = bot.change_password(user_id, old_password, new_password, email)

            if success:
                flash(message, "success")
                if is_reset:
                    session.pop('reset_user_id', None)
                return redirect(url_for('index'))
            else:
                flash(message, "error")

    return render_template('change_password.html', is_reset=is_reset)

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        user_id = request.form.get('username')
        email = request.form.get('email')

        if 'check' in request.form:
            user = bot.users.get(user_id)
            if not user or user['email'] != email:
                flash("Usuario o email incorrectos.", "error")
                return redirect(url_for('forgot_password'))

            session['reset_user_id'] = user_id
            return render_template('forgot_password.html',
                                   show_questions=True,
                                   security_questions=user['security_questions'])

        elif 'reset' in request.form:
            user_id = session.get('reset_user_id')
            user = bot.users.get(user_id)
            if not user:
                flash("Sesión expirada. Por favor, intente de nuevo.", "error")
                return redirect(url_for('forgot_password'))

            correct_answers = 0
            for i, q in enumerate(user['security_questions']):
                answer = request.form.get(f'answer_{i}')
                if q['answer'] == hashlib.sha256(answer.encode()).hexdigest():
                    correct_answers += 1

            if correct_answers != 2:
                flash("Respuestas incorrectas a las preguntas de seguridad.", "error")
                return redirect(url_for('forgot_password'))

            session['user_id'] = user_id
            flash("Puede cambiar su contraseña ahora.", "success")
            return redirect(url_for('change_password'))

    return render_template('forgot_password.html', show_questions=False)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user_id = request.form.get('username')
        password = request.form.get('password')

        if not user_id or not password:
            flash("Usuario y contraseña son requeridos.", "error")
            return redirect(url_for('login'))

        try:
            if bot.authenticate_user(user_id, password):
                session['user_id'] = user_id
                flash(f"Bienvenido, {user_id}!", "success")
                return redirect(url_for('index'))
            else:
                flash("Credenciales incorrectas.", "error")
        except Exception as e:
            logging.error(f"Error al iniciar sesión para el usuario {user_id}: {str(e)}")
            flash("Ocurrió un error al iniciar sesión. Por favor, contacte al administrador.", "error")
            return redirect(url_for('login'))

    return render_template('login.html')


@app.route('/start_exchange', methods=['POST'])
@login_required
def start_exchange():
    user_id = session['user_id']
    exchange_id = request.form.get('exchange_id')

    # Marcar al usuario como activo
    bot.mark_user_active(user_id)

    # Verificar si la configuración del usuario existe, si no, cargarla
    if user_id not in bot.users_exchanges_config:
        try:
            bot.load_encrypted_config(user_id)
            bot.initialize_structures(user_id)
            # Configurar límites de tareas
            bot.configure_user_limits(user_id)
            logging.info(f"Usuario {user_id}: Configuración cargada bajo demanda")
        except Exception as e:
            logging.error(f"Usuario {user_id}: Error al cargar configuración: {str(e)}")
            return jsonify({"success": False, "message": f"Error al cargar la configuración: {str(e)}"})

    # Verificar si el exchange existe para este usuario
    if exchange_id not in bot.users_exchanges_config[user_id]:
        logging.error(f"Usuario {user_id}: Exchange '{exchange_id}' no encontrado en la configuración")
        return jsonify({"success": False, "message": f"Exchange '{exchange_id}' no configurado para este usuario."})

    if bot.users_exchanges_config[user_id][exchange_id]['active']:
        if bot.loop.is_closed():
            bot.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(bot.loop)

        asyncio.run_coroutine_threadsafe(bot.start_single_exchange(user_id, exchange_id), bot.loop)
        return jsonify({"success": True, "message": f"Exchange '{exchange_id}' iniciado exitosamente."})
    else:
        return jsonify(
            {"success": False, "message": f"Exchange '{exchange_id}' está deshabilitado y no se puede iniciar."})

@app.route('/stop_exchange', methods=['POST'])
@login_required
def stop_exchange():
    user_id = session['user_id']
    exchange_id = request.form.get('exchange_id')
    if exchange_id in bot.users_exchanges_config[user_id]:
        coro = bot.stop_exchange_task_async(user_id, exchange_id)
        future = asyncio.run_coroutine_threadsafe(coro, bot.loop)
        try:
            result = future.result(timeout=10)
            if result:
                return jsonify({"success": True, "message": f"Exchange '{exchange_id}' detenido exitosamente."})
            else:
                return jsonify({"success": False, "message": f"No se pudo detener el exchange '{exchange_id}'."})
        except Exception as e:
            logging.error(f"Error al detener el exchange {exchange_id}: {e}")
            return jsonify({"success": False, "message": f"Error al detener el exchange '{exchange_id}': {str(e)}"})
    return jsonify({"success": False, "message": f"Exchange '{exchange_id}' no encontrado."})

@app.route('/add_exchange', methods=['GET', 'POST'])
@login_required
def add_exchange_route():
    user_id = session['user_id']
    if request.method == 'POST':
        exchange_id = request.form.get('id')
        name = request.form.get('name').lower()
        api_key = request.form.get('api_key')
        secret = request.form.get('secret')
        password = request.form.get('password') or ''

        if not all([exchange_id, name, api_key, secret]):
            flash("Faltan campos para agregar el exchange.", "error")
            return redirect(url_for('add_exchange_route'))

        result = bot.add_exchange(user_id, [exchange_id, name, api_key, secret, password])

        if result:
            flash(result, "error")
        else:
            flash(f"Exchange '{exchange_id}' agregado exitosamente.", "success")
        return redirect(url_for('index'))

    return render_template('add_exchange.html')

@app.route('/edit_exchange/<exchange_id>', methods=['GET', 'POST'])
@login_required
def edit_exchange_route(exchange_id):
    user_id = session['user_id']
    if request.method == 'POST':
        api_key = request.form.get('api_key')
        secret = request.form.get('secret')
        password = request.form.get('password') or ''

        if not all([api_key, secret]):
            flash("Faltan campos para editar el exchange.", "error")
            return redirect(url_for('edit_exchange_route', exchange_id=exchange_id))

        bot.edit_exchange(user_id, [exchange_id, api_key, secret, password])
        flash(f"Exchange '{exchange_id}' editado exitosamente.", "success")
        return redirect(url_for('index'))

    exchange = bot.users_exchanges_config[user_id].get(exchange_id)
    if not exchange:
        flash(f"Exchange '{exchange_id}' no encontrado.", "error")
        return redirect(url_for('index'))
    return render_template('edit_exchange.html', exchange_id=exchange_id, exchange=exchange)


@app.route('/delete_exchange/<exchange_id>', methods=['POST'])
@login_required
def delete_exchange_route(exchange_id):
    user_id = session['user_id']

    # 1) Si está corriendo, lo detenemos primero
    if bot.users_exchange_running_status[user_id].get(exchange_id, False):
        coro = bot.stop_exchange_task_async(user_id, exchange_id)
        future = asyncio.run_coroutine_threadsafe(coro, bot.loop)
        try:
            result = future.result(timeout=10)
            if not result:
                flash(f"No se pudo detener el exchange '{exchange_id}'.", "error")
                return redirect(url_for('index'))
        except Exception as e:
            logging.error(f"Error al detener el exchange '{exchange_id}' antes de eliminarlo: {e}")
            flash(f"Error al detener el exchange '{exchange_id}' antes de eliminarlo: {str(e)}", "error")
            return redirect(url_for('index'))

    # 2) Ahora sí, borramos su configuración
    bot.delete_exchange(user_id, [exchange_id])

    flash(f"Exchange '{exchange_id}' eliminado.", "success")
    return redirect(url_for('index'))


@app.route('/start_token', methods=['POST'])
@login_required
def start_token_route():
    user_id = session['user_id']
    exchange_id = request.form.get('exchange_id')
    symbol = request.form.get('symbol')

    # Marcar al usuario como activo
    bot.mark_user_active(user_id)

    # Validaciones básicas
    if exchange_id not in bot.users_exchanges_config[user_id]:
        return jsonify({"success": False, "message": f"Exchange '{exchange_id}' no encontrado."})

    if symbol not in bot.users_exchanges_config[user_id][exchange_id]['symbols']:
        return jsonify({"success": False, "message": f"Token '{symbol}' no asociado a {exchange_id}."})

    # Llamamos a la función asíncrona
    coro = bot.start_symbol_task(user_id, exchange_id, symbol)
    future = asyncio.run_coroutine_threadsafe(coro, bot.loop)
    try:
        result = future.result(timeout=10)
        if result is True:
            # Se inició OK
            return jsonify({"success": True, "message": f"Token '{symbol}' en '{exchange_id}' iniciado."})
        else:
            # No se pudo iniciar (porque estaba corriendo o deshabilitado)
            return jsonify({"success": False, "message": f"No se pudo iniciar el token '{symbol}' en '{exchange_id}'."})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route('/stop_token', methods=['POST'])
@login_required
def stop_token_route():
    user_id = session['user_id']
    exchange_id = request.form.get('exchange_id')
    symbol = request.form.get('symbol')

    coro = bot.stop_symbol_task(user_id, exchange_id, symbol)
    future = asyncio.run_coroutine_threadsafe(coro, bot.loop)
    try:
        result = future.result(timeout=10)
        if result:
            return jsonify({"success": True, "message": f"Token '{symbol}' en '{exchange_id}' detenido."})
        else:
            return jsonify({"success": False, "message": f"Token '{symbol}' no estaba corriendo."})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

################################################
# app.py
################################################
@app.route('/view_exchange/<exchange_id>')
@login_required
def view_exchange(exchange_id):
    user_id = session['user_id']

    # Marcar al usuario como activo
    bot.mark_user_active(user_id)

    # 1) Verificar que user_id existe en las configs
    if user_id not in bot.users_exchanges_config:
        bot.load_encrypted_config(user_id)
        bot.initialize_structures(user_id)

    # 2) Revisar si existe este exchange_id
    exchange = bot.users_exchanges_config[user_id].get(exchange_id)
    if not exchange:
        flash(f"Exchange '{exchange_id}' no encontrado o no configurado.", "error")
        return redirect(url_for('index'))

    # 3) Si no existe 'symbols' en la config del exchange, forzarlo
    if 'symbols' not in exchange:
        exchange['symbols'] = []

    # 4) Construir la lista de tokens
    tokens = [token for token in bot.users_symbols_config[user_id] if exchange_id in token.get('exchanges', [])]

    # 5) Cargar PnL, etc.
    exchange_pnl = bot.users_profit_loss.get(user_id, {}).get(exchange_id, {})
    reinvested_profits = bot.users_reinvested_profits.get(user_id, {}).get(exchange_id, {})

    # 6) Diccionario de status de *exchanges*
    exchanges_config = bot.users_exchanges_config[user_id]
    status = {
        ex_id: bot.users_exchange_running_status[user_id].get(ex_id, False)
        for ex_id in exchanges_config.keys()
    }

    # 7) Construir las órdenes abiertas
    open_orders = {}

    def process_symbol(symbol):
        buy_orders = bot.users_order_trackers[user_id].get_open_buy_orders(exchange_id, symbol)
        pending_sells = bot.users_pending_sells[user_id].get(exchange_id, {}).get(symbol, [])

        # Verificar si este símbolo usa estrategia Infinity
        symbol_config = next((s for s in bot.users_symbols_config[user_id] if s['symbol'] == symbol), None)
        is_infinity = symbol_config and symbol_config.get('strategy') == 'infinity'

        # Si es Infinity, obtener órdenes directamente del exchange
        if is_infinity:
            try:
                exchange = bot.users_exchanges[user_id][exchange_id]
                # Ejecutar en un coroutine separado con timeout
                future = asyncio.run_coroutine_threadsafe(
                    exchange.fetch_open_orders(symbol),
                    bot.loop
                )
                infinity_orders = future.result(timeout=5)

                # Procesar órdenes de infinity
                infinity_buy_orders = {}
                infinity_sell_orders = {}

                for order in infinity_orders:
                    if order['side'] == 'buy':
                        infinity_buy_orders[order['id']] = {
                            'id': order['id'],
                            'amount': order['amount'],
                            'price': order['price'],
                            'status': order['status']
                        }
                    elif order['side'] == 'sell':
                        infinity_sell_orders[order['id']] = {
                            'id': order['id'],
                            'amount': order['amount'],
                            'price': order['price'],
                            'status': order['status']
                        }

                # Combinar con las estructuras existentes
                buy_orders.update(infinity_buy_orders)
                sell_orders = infinity_sell_orders

                logging.info(
                    f"Usuario {user_id}: Órdenes Infinity para {symbol}: Compras={len(infinity_buy_orders)}, Ventas={len(infinity_sell_orders)}")
            except Exception as e:
                logging.error(f"Usuario {user_id}: Error al obtener órdenes Infinity para {symbol}: {e}")
                # Si hay error, usar solo las órdenes originales
                sell_orders = {}
                for order in pending_sells:
                    sell_orders[order['id']] = {
                        'id': order['id'],
                        'amount': order['amount'],
                        'price': order['price'],
                        'status': order.get('status', 'open')
                    }
        else:
            # Para estrategias normales usar el método habitual
            sell_orders = {}
            for order in pending_sells:
                sell_orders[order['id']] = {
                    'id': order['id'],
                    'amount': order['amount'],
                    'price': order['price'],
                    'status': order.get('status', 'open')
                }

        orders = {'buy': buy_orders, 'sell': sell_orders}
        logging.info(
            f"Usuario {user_id}: Órdenes para {symbol} en {exchange_id}: "
            f"Compras={len(buy_orders)}, Ventas={len(sell_orders)}"
        )
        return symbol, orders

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = executor.map(process_symbol, exchange['symbols'])

    for symbol, orders in results:
        open_orders[symbol] = orders

    # 8) Diccionario con el "running status" de cada token
    if user_id not in bot.users_token_running_status:
        bot.users_token_running_status[user_id] = {}
    if exchange_id not in bot.users_token_running_status[user_id]:
        bot.users_token_running_status[user_id][exchange_id] = {}

    token_running_status = bot.users_token_running_status[user_id][exchange_id]

    # 9) Render
    return render_template(
        'view_exchange.html',
        exchange_id=exchange_id,
        tokens=tokens,
        exchange_pnl=exchange_pnl,
        open_orders=open_orders,
        reinvested_profits=reinvested_profits,
        user_id=user_id,
        exchanges_config=exchanges_config,
        status=status,
        bot=bot,
        token_running_status=token_running_status
    )

@app.route('/add_token/<exchange_id>', methods=['GET', 'POST'])
@login_required
def add_token_route(exchange_id):
    user_id = session['user_id']
    if user_id not in bot.users_exchanges_config:
        bot.load_encrypted_config(user_id)
        bot.initialize_structures(user_id)

    exchanges = bot.users_exchanges_config[user_id]
    logging.info(f"Exchanges disponibles para el usuario {user_id}: {exchanges}")

    if request.method == 'POST':
        # 1) Obtener los valores del formulario
        symbol = request.form.get('symbol')
        strategy = request.form.get('strategy')

        # Definir requerimientos base y específicos según estrategia
        required_fields = ['symbol', 'strategy']
        if strategy in ['strategy1', 'strategy2', 'strategy4']:
            required_fields.append('trade_amount')
        elif strategy == 'compound':
            required_fields += ['initial_capital', 'spread', 'take_profit', 'max_orders', 'order_expiration']
        elif strategy == 'infinity':
            required_fields += ['total_balance_usdt', 'grid_interval', 'min_price', 'check_interval', 'commission',
                                 'reinvestment_percentage', 'max_reinvestment_pct', 'reserve_percentage']

        missing_fields = [field for field in required_fields if not request.form.get(field)]
        if missing_fields:
            flash(f"Faltan campos requeridos: {', '.join(missing_fields)}", "error")
            return redirect(url_for('add_token_route', exchange_id=exchange_id))

        # Parámetros comunes
        daily_loss_max = request.form.get('daily_loss_max')
        reactivation_threshold = request.form.get('reactivation_threshold')

        # Parámetros para estrategias strategy1, strategy2, strategy4 y compound
        spread = request.form.get('spread')
        take_profit = request.form.get('take_profit')
        trade_amount = request.form.get('trade_amount')
        max_orders = request.form.get('max_orders')
        max_sell_orders = request.form.get('max_sell_orders')
        order_expiration = request.form.get('order_expiration')

        # Parámetros exclusivos para compound
        initial_capital_str = request.form.get('initial_capital', '5000.0') if strategy == 'compound' else None
        reinvestment_percentage = request.form.get('reinvestment_percentage', '75.0') if strategy == 'compound' else None
        max_reinvestment_pct = request.form.get('max_reinvestment_pct', '50.0') if strategy == 'compound' else None
        reserve_percentage = request.form.get('reserve_percentage', '20.0') if strategy == 'compound' else None

        # Parámetros exclusivos para infinity
        total_balance_usdt = request.form.get('total_balance_usdt') if strategy == 'infinity' else None
        grid_interval = request.form.get('grid_interval') if strategy == 'infinity' else None
        min_price = request.form.get('min_price') if strategy == 'infinity' else None
        check_interval = request.form.get('check_interval') if strategy == 'infinity' else None
        commission = request.form.get('commission') if strategy == 'infinity' else None
        reinvestment_percentage_inf = request.form.get('reinvestment_percentage') if strategy == 'infinity' else None
        max_reinvestment_pct_inf = request.form.get('max_reinvestment_pct') if strategy == 'infinity' else None
        reserve_percentage_inf = request.form.get('reserve_percentage') if strategy == 'infinity' else None

        # Conversión de tipos
        try:
            if strategy in ['strategy1', 'strategy2', 'strategy4', 'compound']:
                if spread is not None:
                    spread = float(spread)
                if take_profit is not None:
                    take_profit = float(take_profit)
                if trade_amount and strategy in ['strategy1', 'strategy2', 'strategy4']:
                    trade_amount = float(trade_amount)
                if max_orders is not None:
                    max_orders = int(max_orders)
                if max_sell_orders is not None:
                    max_sell_orders = int(max_sell_orders)
                if order_expiration is not None:
                    order_expiration = int(order_expiration)
            if daily_loss_max:
                daily_loss_max = float(daily_loss_max)
            if reactivation_threshold:
                reactivation_threshold = float(reactivation_threshold)

            if strategy == 'compound':
                initial_capital = float(initial_capital_str) if initial_capital_str else 5000.0
                reinvestment_percentage = float(reinvestment_percentage) if reinvestment_percentage else 75.0
                max_reinvestment_pct = float(max_reinvestment_pct) if max_reinvestment_pct else 50.0
                reserve_percentage = float(reserve_percentage) if reserve_percentage else 20.0
            elif strategy == 'infinity':
                total_balance_usdt = float(total_balance_usdt) if total_balance_usdt else 1000.0
                grid_interval = float(grid_interval) if grid_interval else 0.002
                min_price = float(min_price) if min_price else 8000.0
                check_interval = float(check_interval) if check_interval else 5
                commission = float(commission) if commission else 0.001
                reinvestment_percentage_inf = float(reinvestment_percentage_inf) if reinvestment_percentage_inf else 75.0
                max_reinvestment_pct_inf = float(max_reinvestment_pct_inf) if max_reinvestment_pct_inf else 50.0
                reserve_percentage_inf = float(reserve_percentage_inf) if reserve_percentage_inf else 20.0
            else:
                # Para otras estrategias, no se requiere conversión adicional
                pass
        except ValueError as ve:
            flash(f"Error en la conversión de tipos: {ve}", "error")
            return redirect(url_for('add_token_route', exchange_id=exchange_id))

        # Preparar data para bot.add_token según estrategia
        token_data = {
            'exchange_id': exchange_id,
            'symbol': symbol,
            'daily_loss_max': daily_loss_max,
            'reactivation_threshold': reactivation_threshold,
            'strategy': strategy
        }
        # Para estrategias que requieren trade_amount (strategy1,2,4)
        if strategy in ['strategy1', 'strategy2', 'strategy4']:
            token_data.update({
                'spread': spread,
                'take_profit': take_profit,
                'trade_amount': trade_amount,
                'max_orders': max_orders,
                'max_sell_orders': max_sell_orders,
                'order_expiration': order_expiration
            })
        elif strategy == 'compound':
            token_data.update({
                'initial_capital': initial_capital,
                'spread': spread,
                'take_profit': take_profit,
                'max_orders': max_orders,
                'order_expiration': order_expiration,
                'reinvestment_percentage': reinvestment_percentage,
                'max_reinvestment_pct': max_reinvestment_pct,
                'reserve_percentage': reserve_percentage
            })
        elif strategy == 'infinity':
            token_data.update({
                'total_balance_usdt': total_balance_usdt,
                'grid_interval': grid_interval,
                'min_price': min_price,
                'check_interval': check_interval,
                'commission': commission,
                'reinvestment_percentage': reinvestment_percentage_inf,
                'max_reinvestment_pct': max_reinvestment_pct_inf,
                'reserve_percentage': reserve_percentage_inf
            })

        result = bot.add_token(user_id, token_data)
        if result and "exitosamente" in result:
            flash(result + f" Estrategia seleccionada: {strategy}", "success")
        elif result:
            flash(result, "error")
        else:
            flash("Token agregado exitosamente.", "success")

        return redirect(url_for('view_exchange', exchange_id=exchange_id))

    logging.info(f"Renderizando add_token.html con exchanges: {exchanges}")
    return render_template('add_token.html', exchange_id=exchange_id, user_id=user_id, exchanges_config=exchanges)

@app.route('/toggle_exchange/<exchange_id>', methods=['POST'])
@login_required
def toggle_exchange(exchange_id):
    user_id = session['user_id']
    if exchange_id in bot.users_exchanges_config[user_id]:
        current_status = bot.users_exchanges_config[user_id][exchange_id]['active']
        new_status = not current_status
        bot.users_exchanges_config[user_id][exchange_id]['active'] = new_status
        bot.save_encrypted_config(user_id)
        status_msg = "habilitado" if new_status else "deshabilitado"
        flash(f"Exchange '{exchange_id}' ha sido {status_msg}.", "success")

        return jsonify(
            {"success": True, "message": f"Exchange '{exchange_id}' ha sido {status_msg}.", "is_active": new_status})
    else:
        return jsonify({"success": False, "message": f"Exchange '{exchange_id}' no encontrado."})


@app.route('/edit_token/<exchange_id>/<path:old_symbol>', methods=['GET', 'POST'])
@login_required
def edit_token_route(exchange_id, old_symbol):
    user_id = session['user_id']
    old_symbol = unquote(old_symbol)

    # Verificar que exista la configuración para el usuario en users_symbols_config
    if user_id not in bot.users_symbols_config:
        flash("No se encontró configuración para este usuario", "error")
        return redirect(url_for('view_exchange', exchange_id=exchange_id))

    if request.method == 'POST':
        strategy = request.form.get('strategy')
        new_symbol = request.form.get('new_symbol')
        exchanges = request.form.getlist('exchanges')

        # Definir requerimientos base y específicos según estrategia
        required_fields = ['new_symbol', 'strategy']
        if strategy in ['strategy1', 'strategy2', 'strategy4']:
            required_fields.append('trade_amount')
        elif strategy == 'compound':
            required_fields += ['initial_capital', 'spread', 'take_profit', 'max_orders', 'order_expiration']
        elif strategy == 'infinity':
            required_fields += ['total_balance_usdt', 'grid_interval', 'min_price', 'check_interval', 'commission',
                                'reinvestment_percentage', 'max_reinvestment_pct', 'reserve_percentage']

        missing_fields = [field for field in required_fields if not request.form.get(field)]
        if missing_fields:
            flash(f"Faltan campos requeridos: {', '.join(missing_fields)}", "error")
            return redirect(url_for('edit_token_route', exchange_id=exchange_id, old_symbol=old_symbol))

        # Parámetros comunes
        daily_loss_max = request.form.get('daily_loss_max')
        reactivation_threshold = request.form.get('reactivation_threshold')

        # Parámetros para estrategias tipo strategy1,2,4 y compound
        spread = request.form.get('spread')
        take_profit = request.form.get('take_profit')
        trade_amount = request.form.get('trade_amount')
        max_orders = request.form.get('max_orders')
        max_sell_orders = request.form.get('max_sell_orders')
        order_expiration = request.form.get('order_expiration')

        # Para compound
        initial_capital_str = request.form.get('initial_capital', '5000.0') if strategy == 'compound' else None
        reinvestment_percentage = request.form.get('reinvestment_percentage', '75.0') if strategy == 'compound' else None
        max_reinvestment_pct = request.form.get('max_reinvestment_pct', '50.0') if strategy == 'compound' else None
        reserve_percentage = request.form.get('reserve_percentage', '20.0') if strategy == 'compound' else None

        # Para infinity
        total_balance_usdt = request.form.get('total_balance_usdt') if strategy == 'infinity' else None
        grid_interval = request.form.get('grid_interval') if strategy == 'infinity' else None
        min_price = request.form.get('min_price') if strategy == 'infinity' else None
        check_interval = request.form.get('check_interval') if strategy == 'infinity' else None
        commission = request.form.get('commission') if strategy == 'infinity' else None
        reinvestment_percentage_inf = request.form.get('reinvestment_percentage') if strategy == 'infinity' else None
        max_reinvestment_pct_inf = request.form.get('max_reinvestment_pct') if strategy == 'infinity' else None
        reserve_percentage_inf = request.form.get('reserve_percentage') if strategy == 'infinity' else None

        try:
            if spread:
                spread = float(spread)
            if take_profit:
                take_profit = float(take_profit)
            if trade_amount and strategy in ['strategy1', 'strategy2', 'strategy4']:
                trade_amount = float(trade_amount)
            if max_orders:
                max_orders = int(max_orders)
            if max_sell_orders:
                max_sell_orders = int(max_sell_orders)
            if order_expiration:
                order_expiration = int(order_expiration)
            if daily_loss_max:
                daily_loss_max = float(daily_loss_max)
            if reactivation_threshold:
                reactivation_threshold = float(reactivation_threshold)

            if strategy == 'compound':
                initial_capital = float(initial_capital_str) if initial_capital_str else 5000.0
                reinvestment_percentage = float(reinvestment_percentage) if reinvestment_percentage else 75.0
                max_reinvestment_pct = float(max_reinvestment_pct) if max_reinvestment_pct else 50.0
                reserve_percentage = float(reserve_percentage) if reserve_percentage else 20.0
            elif strategy == 'infinity':
                total_balance_usdt = float(total_balance_usdt) if total_balance_usdt else 1000.0
                grid_interval = float(grid_interval) if grid_interval else 0.002
                min_price = float(min_price) if min_price else 8000.0
                check_interval = float(check_interval) if check_interval else 5
                commission = float(commission) if commission else 0.001
                reinvestment_percentage_inf = float(reinvestment_percentage_inf) if reinvestment_percentage_inf else 75.0
                max_reinvestment_pct_inf = float(max_reinvestment_pct_inf) if max_reinvestment_pct_inf else 50.0
                reserve_percentage_inf = float(reserve_percentage_inf) if reserve_percentage_inf else 20.0
            else:
                pass
        except ValueError as ve:
            flash(f"Error en la conversión de tipos: {ve}", "error")
            return redirect(url_for('edit_token_route', exchange_id=exchange_id, old_symbol=old_symbol))

        token_data = {
            'exchange_id': exchange_id,
            'old_symbol': old_symbol,
            'new_symbol': new_symbol,
            'daily_loss_max': daily_loss_max,
            'reactivation_threshold': reactivation_threshold,
            'strategy': strategy,
            'exchanges': exchanges
        }
        if strategy in ['strategy1', 'strategy2', 'strategy4']:
            token_data.update({
                'spread': spread,
                'take_profit': take_profit,
                'trade_amount': trade_amount,
                'max_orders': max_orders,
                'max_sell_orders': max_sell_orders,
                'order_expiration': order_expiration
            })
        elif strategy == 'compound':
            token_data.update({
                'initial_capital': initial_capital,
                'spread': spread,
                'take_profit': take_profit,
                'max_orders': max_orders,
                'order_expiration': order_expiration,
                'reinvestment_percentage': reinvestment_percentage,
                'max_reinvestment_pct': max_reinvestment_pct,
                'reserve_percentage': reserve_percentage
            })
        elif strategy == 'infinity':
            token_data.update({
                'total_balance_usdt': total_balance_usdt,
                'grid_interval': grid_interval,
                'min_price': min_price,
                'check_interval': check_interval,
                'commission': commission,
                'reinvestment_percentage': reinvestment_percentage_inf,
                'max_reinvestment_pct': max_reinvestment_pct_inf,
                'reserve_percentage': reserve_percentage_inf
            })

        result = bot.edit_token(user_id, token_data)
        if result and "exitosamente" in result:
            flash(result + f" Estrategia actualizada: {strategy}", "success")
        elif result:
            flash(result, "error")
        else:
            flash("Token editado exitosamente.", "success")

        return redirect(url_for('view_exchange', exchange_id=exchange_id))

    else:
        # Obtener la lista de tokens del usuario sin riesgo de KeyError
        user_tokens = bot.users_symbols_config.get(user_id)
        if not user_tokens:
            flash("No se encontró configuración para este usuario", "error")
            return redirect(url_for('view_exchange', exchange_id=exchange_id))

        token = next((item for item in user_tokens
                      if item['symbol'] == old_symbol and exchange_id in item['exchanges']), None)
        if not token:
            flash(f"Token '{old_symbol}' no encontrado en el exchange '{exchange_id}'.", "error")
            return redirect(url_for('view_exchange', exchange_id=exchange_id))

        return render_template('edit_token.html',
                               exchange_id=exchange_id,
                               old_symbol=old_symbol,
                               token=token,
                               user_id=user_id,
                               exchanges_config=bot.users_exchanges_config.get(user_id, {}))


@app.route('/cancel_order', methods=['POST'])
def cancel_order_endpoint():
    user_id = session.get('user_id')
    exchange_id = request.form.get('exchange_id')
    symbol = request.form.get('symbol')
    order_id = request.form.get('order_id')

    if not all([exchange_id, symbol, order_id]):
        flash("Faltan parámetros para cancelar la orden.", "error")
        return redirect(url_for('view_exchange', exchange_id=exchange_id))

    coro = bot.cancel_order_async(user_id, order_id, symbol, exchange_id)
    future = asyncio.run_coroutine_threadsafe(coro, bot.loop)
    try:
        future.result(timeout=10)
        flash(f"La orden {order_id} fue cancelada con éxito.", "success")
    except Exception as e:
        logging.error(f"Error al cancelar la orden {order_id}: {e}")
        flash(f"Error al cancelar la orden {order_id}: {str(e)}", "error")

    # Redirigimos de nuevo a la vista del exchange para recargar.
    return redirect(url_for('view_exchange', exchange_id=exchange_id))


@app.route('/delete_token/<exchange_id>/<path:symbol>', methods=['POST'])
@login_required
def delete_token_route(exchange_id, symbol):
    user_id = session['user_id']
    symbol = unquote(symbol)

    # Ejecuta la corrutina delete_token(...) de forma síncrona:
    result = asyncio.run(bot.delete_token(user_id, [exchange_id, symbol]))

    # Ahora 'result' es un string, no un objeto coroutine
    if "eliminado" in result:
        flash(result, "success")
    else:
        flash(result, "error")

    return redirect(url_for('view_exchange', exchange_id=exchange_id))

def parse_optional_float(value):
    if value in (None, '', 'None'):
        return None
    else:
        try:
            return float(value)
        except ValueError:
            logging.error(f"Valor inválido para conversión a float: {value}")
            return None

@app.route('/status')
@login_required
def status_route():
    user_id = session['user_id']
    status = {exchange_id: bot.users_exchange_running_status[user_id].get(exchange_id, False) for exchange_id in bot.users_exchanges_config[user_id].keys()}
    return jsonify(status)

@app.route('/exchange_pnl/<exchange_id>')
@login_required
def exchange_pnl(exchange_id):
    user_id = session['user_id']
    transactions = bot.load_transactions(user_id, exchange_id)

    # Modificar esta parte para incluir PnL de Infinity
    total_pnl = sum(t.get('pnl', 0) for t in transactions)

    # Identificar tokens Infinity
    infinity_tokens = [t['symbol'] for t in bot.users_symbols_config[user_id]
                      if t.get('strategy') == 'infinity' and exchange_id in t.get('exchanges', [])]

    # Obtener todos los símbolos para los que hay transacciones
    symbols = list(set(t['symbol'] for t in transactions if 'symbol' in t))

    # Crear datos para los gráficos
    dates = {symbol: [] for symbol in symbols}
    pnl_data = {symbol: [] for symbol in symbols}

    for symbol in symbols:
        # Verificar si existe un token con estrategia infinity para este símbolo
        symbol_config = next((t for t in bot.users_symbols_config[user_id] if t['symbol'] == symbol), None)
        is_infinity = symbol_config and symbol_config.get('strategy') == 'infinity'

        # Obtener PnL específico para tokens infinity
        if is_infinity:
            # Obtener el ROI para este token infinity
            roi = bot.get_infinity_roi(user_id, exchange_id, symbol)
            # Añadir a los datos de PnL
            if roi is not None:
                pnl_data[symbol].append(roi)
                # Añadir una fecha para el punto de datos
                dates[symbol].append(datetime.now().strftime('%Y-%m-%d'))

        # Para tokens no-infinity, procesar transacciones normales
        symbol_transactions = [t for t in transactions if t.get('symbol') == symbol]
        for transaction in symbol_transactions:
            if 'timestamp' in transaction and 'pnl' in transaction:
                date_str = transaction['timestamp'].split('T')[0]  # formato YYYY-MM-DD
                dates[symbol].append(date_str)
                pnl_data[symbol].append(transaction['pnl'])

    return render_template('exchange_pnl.html',
                           exchange_id=exchange_id,
                           transactions=transactions,
                           total_pnl=total_pnl,
                           user_id=user_id,
                           symbols=symbols,
                           dates=dates,
                           pnl_data=pnl_data,
                           infinity_tokens=infinity_tokens,
                           bot=bot)

@app.route('/toggle_token/<exchange_id>/<path:symbol>', methods=['POST'])
@login_required
def toggle_token_route(exchange_id, symbol):
    user_id = session['user_id']
    symbol = unquote(symbol)
    result = bot.toggle_token(user_id, exchange_id, symbol)
    if result and "ha sido" in result:
        flash(result, "success")
    elif result:
        flash(result, "error")
    else:
        flash(f"Token '{symbol}' no encontrado en el exchange '{exchange_id}'.", "error")
    return redirect(url_for('view_exchange', exchange_id=exchange_id))

@app.route('/token_status')
@login_required
def token_status():
    user_id = session['user_id']
    exchange_id = request.args.get('exchange_id')
    symbol = request.args.get('symbol')
    # Aquí se asume que el estado del token está en bot.users_token_running_status
    running = bot.users_token_running_status.get(user_id, {}).get(exchange_id, {}).get(symbol, False)
    return jsonify({"running": running})

@app.route('/list_routes')
def list_routes():
    import urllib
    output = []
    for rule in app.url_map.iter_rules():
        methods = ','.join(rule.methods)
        line = urllib.parse.unquote(f"{rule.endpoint:30s} {methods:20s} {rule}")
        output.append(line)
    return "<br>".join(output)

if __name__ == '__main__':

    # Función para ejecutar Flask
    def run_flask():
        app.run(host='0.0.0.0', port=5003, debug=False, use_reloader=False)

    # Iniciar Flask en un hilo separado
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()

    # Iniciar el optimizador de memoria
    asyncio.run_coroutine_threadsafe(bot.memory_optimizer(), loop)

    try:
        # Ejecutar el loop de eventos
        loop.run_forever()
    except KeyboardInterrupt:
        logging.info("Cierre de la aplicación por el usuario")
    finally:
        # Asegurarse de cerrar correctamente
        for user_id in bot.users:
            loop.run_until_complete(bot.shutdown_bot(user_id))
        loop.close()