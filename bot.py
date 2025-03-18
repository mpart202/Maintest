import ccxt
import ccxt.async_support as ccxt_async
import asyncio
import time
import logging
import json
import os
import re
import platform
import bcrypt
import hashlib
import joblib
import pandas as pd
from datetime import datetime, timedelta
from collections import deque, defaultdict
from cryptography.fernet import Fernet, InvalidToken
from functools import lru_cache
from sklearn.model_selection import train_test_split, RandomizedSearchCV
from sklearn.ensemble import RandomForestRegressor
from scipy.stats import randint

# For Windows compatibility
if platform.system() == 'Windows':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)

# Diccionarios globales para almacenar datos por usuario
users = {
    'user_id': {
        'password': 'hashed_password',
        'email': 'user@example.com',
        'security_questions': [
            {'question': 'Pregunta 1', 'answer': 'respuesta_hash'},
            {'question': 'Pregunta 2', 'answer': 'respuesta_hash'}
        ]
    }
}
users = {}
users_exchanges_config = {}
users_symbols_config = {}
users_commission_rate = {}
users_exchanges = {}
users_connection_status = {}
users_daily_trades = {}
users_market_prices = {}
users_predicted_prices = {}
users_open_orders = {}
users_pending_sells = {}
users_daily_losses = {}
users_profit_loss = {}
users_active_symbols = {}
users_reactivation_thresholds = {}
users_exchange_tasks = {}
users_order_trackers = {}
json_directory = 'trading_data'
users_key_file = {}
users_first_sell_order_placed = {}
users_cipher_suite = {}
users_actions_log = {}
users_bot_status = {}
users_symbol_tasks = {}
users_token_running_status = {}
users_exchange_running_status = {}
users_reinvested_profits = {}  # <-- Agrega esta línea
# Semáforos específicos por usuario y exchange
users_rate_limiters = {}

def get_rate_limiter(user_id, exchange_id):
    if user_id not in users_rate_limiters:
        users_rate_limiters[user_id] = {}
    if exchange_id not in users_rate_limiters[user_id]:
        # Crear un semáforo específico para este usuario/exchange
        users_rate_limiters[user_id][exchange_id] = asyncio.Semaphore(3)
    return users_rate_limiters[user_id][exchange_id]

security_questions = [
    "¿Cuál es el nombre de tu primera mascota?",
    "¿En qué ciudad naciste?",
    "¿Cuál es tu color favorito?",
    "¿Cuál es el segundo nombre de tu madre?",
    "¿Cuál fue tu primer automóvil?",
    "¿Cuál es tu película favorita?"
]
users_file = 'users.json'
infinity_strategy_instances = {}

# Estructura para seguimiento de acceso a datos
user_data_access = {}  # {user_id: last_access_timestamp}

# Función para liberar memoria de usuarios inactivos

# Función para liberar memoria de usuarios inactivos
async def memory_optimizer():
    while True:
        current_time = time.time()
        inactive_threshold = 3600  # 1 hora de inactividad

        for user_id, last_access in list(user_data_access.items()):
            if current_time - last_access > inactive_threshold:
                # Usuario inactivo, mover datos a disco
                await offload_user_data(user_id)

        await asyncio.sleep(300)  # Verificar cada 5 minutos

# # # # # # asyncio.create_task(memory_optimizer()) # Comentado para evitar error, se iniciará desde main.py # Comentado para evitar error, se iniciará desde main.py # Comentado para evitar error, se iniciará desde main.py # Comentado para evitar error, se iniciará desde main.py # Comentado para evitar error, se iniciará desde main.py # Comentado para evitar error, se iniciará desde main.py

# Función para descargar datos de usuario a disco
async def offload_user_data(user_id):
    try:
        # Guardar todos los datos en disco
        save_encrypted_config(user_id)
        save_reinvested_profits(user_id)

        # Liberar memoria
        if user_id in users_market_prices:
            del users_market_prices[user_id]
        if user_id in users_predicted_prices:
            del users_predicted_prices[user_id]
        if user_id in users_open_orders:
            del users_open_orders[user_id]
        if user_id in users_pending_sells:
            del users_pending_sells[user_id]
        if user_id in users_daily_trades:
            del users_daily_trades[user_id]
        if user_id in users_daily_losses:
            del users_daily_losses[user_id]

        logging.info(f"Datos del usuario {user_id} descargados a disco por inactividad")
    except Exception as e:
        logging.error(f"Error al descargar datos del usuario {user_id}: {e}")


# Función para registrar actividad de usuario
def mark_user_active(user_id):
    user_data_access[user_id] = time.time()


# Sistema de límite de tareas por usuario
class UserTaskLimiter:
    def __init__(self):
        self.user_limits = {}  # {user_id: {exchange_id: max_tasks}}
        self.user_active_tasks = {}  # {user_id: {exchange_id: current_active_tasks}}

    def initialize_user(self, user_id):
        if user_id not in self.user_limits:
            self.user_limits[user_id] = {}
            self.user_active_tasks[user_id] = {}

    def set_limit(self, user_id, exchange_id, max_tasks):
        self.initialize_user(user_id)
        self.user_limits[user_id][exchange_id] = max_tasks
        if exchange_id not in self.user_active_tasks[user_id]:
            self.user_active_tasks[user_id][exchange_id] = 0

    def increment_tasks(self, user_id, exchange_id):
        self.initialize_user(user_id)
        if exchange_id not in self.user_active_tasks[user_id]:
            self.user_active_tasks[user_id][exchange_id] = 0
        self.user_active_tasks[user_id][exchange_id] += 1

    def decrement_tasks(self, user_id, exchange_id):
        if (user_id in self.user_active_tasks and
                exchange_id in self.user_active_tasks[user_id] and
                self.user_active_tasks[user_id][exchange_id] > 0):
            self.user_active_tasks[user_id][exchange_id] -= 1

    def can_start_task(self, user_id, exchange_id):
        if user_id not in self.user_limits or exchange_id not in self.user_limits[user_id]:
            # Sin límite establecido, permitir por defecto
            return True

        max_tasks = self.user_limits[user_id][exchange_id]
        current_tasks = self.user_active_tasks[user_id].get(exchange_id, 0)

        return current_tasks < max_tasks


# Crear instancia global
task_limiter = UserTaskLimiter()


def configure_user_limits(user_id):
    # Solo configurar límites si el usuario tiene exchanges
    if user_id in users_exchanges_config:
        # Limitar a 10 tareas simultáneas por exchange
        for exchange_id in users_exchanges_config[user_id].keys():
            task_limiter.set_limit(user_id, exchange_id, 10)

# Funciones para gestión de usuarios
def load_users():
    global users
    if os.path.exists(users_file):
        with open(users_file, 'r') as f:
            loaded_users = json.load(f)
            users.update(loaded_users)
    # Cargar ganancias reinvertidas para cada usuario
    for user_id in users.keys():
        load_reinvested_profits(user_id)


# Clase para rastrear órdenes (ahora por usuario)
class OrderTracker:
    def __init__(self):
        self.buy_orders = {}
        self.sell_orders = {}

    def add_buy_order(self, exchange_id, symbol, order_id, amount, price):
        if exchange_id not in self.buy_orders:
            self.buy_orders[exchange_id] = {}
        if symbol not in self.buy_orders[exchange_id]:
            self.buy_orders[exchange_id][symbol] = {}
        self.buy_orders[exchange_id][symbol][order_id] = {
            'id': order_id,
            'symbol': symbol,
            'amount': amount,
            'price': price,
            'placed_time': time.time(),
            'status': 'open'
        }

    def add_sell_order(self, exchange_id, symbol, order_id, amount, price, buy_order_id):
        if exchange_id not in self.sell_orders:
            self.sell_orders[exchange_id] = {}
        if symbol not in self.sell_orders[exchange_id]:
            self.sell_orders[exchange_id][symbol] = {}
        self.sell_orders[exchange_id][symbol][order_id] = {
            'id': order_id,
            'symbol': symbol,
            'amount': amount,
            'price': price,
            'status': 'open',
            'placed_time': time.time(),
            'buy_order_id': buy_order_id
        }

    def update_order_status(self, exchange_id, symbol, order_id, status, is_buy):
        orders = self.buy_orders if is_buy else self.sell_orders
        if (exchange_id in orders and symbol in orders[exchange_id] and order_id in orders[exchange_id][symbol]):
            current_status = orders[exchange_id][symbol][order_id]['status']
            if current_status != status:
                orders[exchange_id][symbol][order_id]['status'] = status
                logging.info(f"Order {order_id} updated to {status}")

    def get_open_buy_orders(self, exchange_id, symbol):
        return {oid: order for oid, order in self.buy_orders.get(exchange_id, {}).get(symbol, {}).items() if order['status'] == 'open'}

    def get_open_sell_orders(self, exchange_id, symbol):
        return {oid: order for oid, order in self.sell_orders.get(exchange_id, {}).get(symbol, {}).items() if order['status'] == 'open'}



def update_bot_status(user_id):
    users_bot_status[user_id] = any(users_exchange_running_status[user_id].values())


def save_users():
    with open(users_file, 'w') as f:
        json.dump(users, f, indent=4)


def register_user(user_id, password, email, security_answers):
    if user_id in users:
        return False, "El usuario ya existe."

    if any(user.get('email') == email for user in users.values() if 'email' in user):
        return False, "El correo electrónico ya está registrado."

    if len(user_id) < 6 or len(user_id) > 20:
        return False, "El nombre de usuario debe tener entre 6 y 20 caracteres."

    if not re.match(r'^(?=.*[A-Z])(?=.*[!@#$%^&*])(?=.{8,})', password):
        return False, "La contraseña debe tener al menos 8 caracteres, una mayúscula y un carácter especial."

    if not re.match(r'^[\w\.-]+@[\w\.-]+\.\w+$', email):
        return False, "El email no es válido."

    hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    # Hashear las respuestas de seguridad
    hashed_security_questions = []
    for qa in security_answers:
        hashed_answer = hashlib.sha256(qa['answer'].encode()).hexdigest()
        hashed_security_questions.append({'question': qa['question'], 'answer': hashed_answer})

    users[user_id] = {
        'password': hashed_password,
        'email': email,
        'security_questions': hashed_security_questions
    }
    save_users()
    initialize_structures(user_id)
    save_encrypted_config(user_id)

    return True, "Usuario registrado exitosamente."


def reset_password(user_id, new_password, email):
    if user_id not in users:
        return False, "Usuario no encontrado."

    user = users[user_id]
    if user['email'] != email:
        return False, "Email incorrecto."

    if not re.match(r'^(?=.*[A-Z])(?=.*[!@#$%^&*])(?=.{8,})', new_password):
        return False, "La nueva contraseña debe tener al menos 8 caracteres, una mayúscula y un carácter especial."

    hashed_password = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    user['password'] = hashed_password
    save_users()

    return True, "Contraseña restablecida exitosamente."


def change_password(user_id, old_password, new_password, email):
    if user_id not in users:
        return False, "Usuario no encontrado."

    user = users[user_id]
    if not bcrypt.checkpw(old_password.encode('utf-8'), user['password'].encode('utf-8')):
        return False, "Contraseña actual incorrecta."

    if user['email'] != email:
        return False, "Email incorrecto."

    if not re.match(r'^(?=.*[A-Z])(?=.*[!@#$%^&*])(?=.{8,})', new_password):
        return False, "La nueva contraseña debe tener al menos 8 caracteres, una mayúscula y un carácter especial."

    hashed_password = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    user['password'] = hashed_password
    save_users()

    return True, "Contraseña cambiada exitosamente."


def verify_security_questions(user_id, answers):
    user = users.get(user_id)
    if not user:
        return False
    for stored_q, provided_a in zip(user['security_questions'], answers):
        if stored_q['answer'] != hashlib.sha256(provided_a.encode()).hexdigest():
            return False
    return True


def authenticate_user(user_id, password):
    logging.info(f"Intentando autenticar usuario: {user_id}")
    logging.info(f"Usuarios disponibles: {list(users.keys())}")
    if user_id not in users:
        logging.error(f"Usuario {user_id} no existe.")
        return False
    stored_password = users[user_id]['password'].encode('utf-8')
    if bcrypt.checkpw(password.encode('utf-8'), stored_password):
        logging.info(f"Usuario {user_id} autenticado exitosamente.")
        return True
    else:
        logging.error(f"Autenticación fallida para el usuario {user_id}.")
        return False


def save_trade(user_id, trade_data, exchange_id):
    if trade_data['status'] == 'closed' and trade_data['side'] == 'buy':
        filename = f"trades_{exchange_id}.json"
        trades = load_json_data(user_id, filename) or []
        trade_data['timestamp'] = datetime.now().isoformat()
        trades.append(trade_data)
        save_json_data(user_id, trades, filename)
        logging.info(f"Usuario {user_id}: Trade guardado para {exchange_id}: {trade_data}")
        saved_trades = load_json_data(user_id, filename)
        if saved_trades and saved_trades[-1] == trade_data:
            logging.info(f"Usuario {user_id}: Verificado: el trade se guardó correctamente")
        else:
            logging.error(f"Usuario {user_id}: Error: el trade no se guardó correctamente")
    else:
        logging.debug(f"Usuario {user_id}: Trade no cumple condiciones para guardado: {trade_data}")


def load_trades(user_id, exchange_id):
    filename = f"trades_{exchange_id}.json"
    return load_json_data(user_id, filename) or []


def save_reinvested_profits(user_id):
    filename = f"reinvested_profits_{user_id}.json"
    data = users_reinvested_profits.get(user_id, {})
    save_json_data(user_id, data, filename)


def load_reinvested_profits(user_id):
    filename = f"reinvested_profits_{user_id}.json"
    data = load_json_data(user_id, filename)
    if data:
        users_reinvested_profits[user_id] = data
        logging.info(f"Usuario {user_id}: Ganancias reinvertidas cargadas exitosamente.")
    else:
        if user_id not in users_reinvested_profits:
            users_reinvested_profits[user_id] = {}
        logging.info(f"Usuario {user_id}: No se encontraron ganancias reinvertidas. Inicializando en 0.")


def load_encrypted_config(user_id):
    encrypted_config_file = f'config_{user_id}.enc'
    key_file = f'encryption_key_{user_id}.key'

    try:
        # Asegurarse de que existe una clave de encriptación para el usuario
        if not os.path.exists(key_file):
            encryption_key = Fernet.generate_key()
            with open(key_file, 'wb') as key_file_obj:
                key_file_obj.write(encryption_key)
        else:
            with open(key_file, 'rb') as key_file_obj:
                encryption_key = key_file_obj.read()

        cipher_suite = Fernet(encryption_key)

        # Si no existe el archivo de configuración, crear uno nuevo
        if not os.path.exists(encrypted_config_file):
            config = {
                'exchanges': {},
                'symbols': [],
                'commission_rate': 0.001
            }
        else:
            # Cargar la configuración existente
            with open(encrypted_config_file, 'rb') as enc_file:
                encrypted_data = enc_file.read()
            decrypted_data = cipher_suite.decrypt(encrypted_data)
            config = json.loads(decrypted_data.decode())

        # Asegurarse de que config es un diccionario
        if not isinstance(config, dict):
            logging.warning(
                f"La configuración cargada para el usuario {user_id} no es un diccionario. Inicializando con valores por defecto.")
            config = {
                'exchanges': {},
                'symbols': [],
                'commission_rate': 0.001
            }

        # NUEVO: Verificar y limpiar duplicados en la configuración
        if 'symbols' in config:
            # Crear un conjunto para detectar duplicados
            token_exchange_pairs = set()
            unique_symbols = []

            for token in config['symbols']:
                # Asegurarnos que exchanges sea una lista
                if 'exchanges' not in token:
                    token['exchanges'] = []

                # Para cada token, filtrar exchanges para evitar duplicados
                valid_exchanges = []
                symbol = token.get('symbol')
                if not symbol:
                    continue  # Ignorar tokens sin símbolo

                for ex_id in token.get('exchanges', []):
                    # Crear un par único (símbolo, exchange)
                    pair = (symbol, ex_id)

                    # Si este par ya existe, omitir este exchange para este token
                    if pair in token_exchange_pairs:
                        logging.warning(
                            f"Usuario {user_id}: Detectado duplicado al cargar: {symbol} en {ex_id}. Ignorando.")
                        continue

                    token_exchange_pairs.add(pair)
                    valid_exchanges.append(ex_id)

                # Actualizar la lista de exchanges con los válidos (no duplicados)
                token['exchanges'] = valid_exchanges

                # Solo agregar tokens que tengan al menos un exchange
                if token['exchanges']:
                    unique_symbols.append(token)

            # Reemplazar la lista de símbolos con la lista depurada
            config['symbols'] = unique_symbols
            logging.info(
                f"Usuario {user_id}: Configuración limpiada. Se conservaron {len(unique_symbols)} tokens únicos.")

        users_exchanges_config[user_id] = config.get('exchanges', {})
        users_symbols_config[user_id] = config.get('symbols', [])
        users_commission_rate[user_id] = config.get('commission_rate', 0.001)

        # NUEVO: Reconstruir lista de símbolos en exchanges
        for exchange_id in users_exchanges_config[user_id]:
            users_exchanges_config[user_id][exchange_id]['symbols'] = []

        for token in users_symbols_config[user_id]:
            for ex_id in token.get('exchanges', []):
                if ex_id in users_exchanges_config[user_id]:
                    if token['symbol'] not in users_exchanges_config[user_id][ex_id]['symbols']:
                        users_exchanges_config[user_id][ex_id]['symbols'].append(token['symbol'])

        migrate_symbols_to_dicts(user_id)
        initialize_structures(user_id)
        initialize_active_exchanges(user_id)

        # NUEVO: Guardar la configuración limpia
        save_encrypted_config(user_id)
        logging.info(f"Configuración cargada y depurada exitosamente para el usuario {user_id}")

    except Exception as e:
        logging.error(f"Error al cargar la configuración para el usuario {user_id}: {str(e)}")
        users_exchanges_config[user_id] = {}
        users_symbols_config[user_id] = []
        users_commission_rate[user_id] = 0.001
        initialize_structures(user_id)
        initialize_active_exchanges(user_id)
        logging.info(f"Inicializada configuración por defecto para el usuario {user_id} debido a un error")

    # Asegurarse de que todas las estructuras necesarias estén inicializadas
    if user_id not in users_exchanges:
        users_exchanges[user_id] = {}
    if user_id not in users_connection_status:
        users_connection_status[user_id] = {}
    if user_id not in users_exchange_running_status:
        users_exchange_running_status[user_id] = {}

# Funciones de encriptación y carga de configuración por usuario
def load_encryption_key(user_id):
    key_file = f'encryption_key_{user_id}.key'
    users_key_file[user_id] = key_file
    if os.path.exists(key_file):
        with open(key_file, 'rb') as key_file_obj:
            return key_file_obj.read()
    else:
        new_key = Fernet.generate_key()
        with open(key_file, 'wb') as key_file_obj:
            key_file_obj.write(new_key)
        return new_key


def save_encrypted_config(user_id):
    config = {
        'exchanges': users_exchanges_config.get(user_id, {}),
        'symbols': users_symbols_config.get(user_id, []),
        'commission_rate': users_commission_rate.get(user_id, 0.001)
    }
    encrypted_config_file = f'config_{user_id}.enc'
    key_file = f'encryption_key_{user_id}.key'

    if not os.path.exists(key_file):
        encryption_key = Fernet.generate_key()
        with open(key_file, 'wb') as key_file_obj:
            key_file_obj.write(encryption_key)
    else:
        with open(key_file, 'rb') as key_file_obj:
            encryption_key = key_file_obj.read()

    cipher_suite = Fernet(encryption_key)

    try:
        encrypted_data = cipher_suite.encrypt(json.dumps(config).encode())
        with open(encrypted_config_file, 'wb') as enc_file:
            enc_file.write(encrypted_data)
        logging.info(f"Configuración guardada exitosamente para el usuario {user_id}")
    except Exception as e:
        logging.error(f"Error al guardar la configuración cifrada para el usuario {user_id}: {e}")


def save_json_data(user_id, data, filename):
    try:
        user_json_directory = os.path.join(json_directory, user_id)
        if not os.path.exists(user_json_directory):
            os.makedirs(user_json_directory)
        filepath = os.path.join(user_json_directory, filename)
        logging.info(f"Datos a guardar en {filepath}: {data}")
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=4)
            f.flush()
            os.fsync(f.fileno())
        logging.info(f"Datos guardados en {filepath}")
        if os.path.exists(filepath):
            logging.info(f"Verificado: el archivo {filepath} existe")
        else:
            logging.error(f"Error: el archivo {filepath} no se creó correctamente")
    except Exception as e:
        logging.error(f"Error al guardar datos en {filename}: {str(e)}")


def calculate_pnl(user_id, buy_order, sell_order, commission_rate):
    try:
        if buy_order['symbol'] != sell_order['symbol']:
            logging.error(
                f"Usuario {user_id}: Símbolos de compra y venta no coinciden: {buy_order['symbol']} vs {sell_order['symbol']}"
            )
            return 0

        buy_cost = buy_order['price'] * buy_order['amount']
        sell_revenue = sell_order['price'] * sell_order['amount']
        # Calcular la comisión para la compra y para la venta, usando la tasa (ej. 0.001)
        commission_buy = commission_rate * buy_cost
        commission_sell = commission_rate * sell_revenue
        pnl = sell_revenue - buy_cost - commission_buy - commission_sell

        if user_id not in users_profit_loss:
            users_profit_loss[user_id] = {}
        if sell_order['symbol'] not in users_profit_loss[user_id]:
            users_profit_loss[user_id][sell_order['symbol']] = 0

        users_profit_loss[user_id][sell_order['symbol']] += pnl
        return pnl
    except Exception as e:
        logging.error(f"Usuario {user_id}: Error al calcular PnL: {str(e)}")
        return 0

def load_transactions(user_id, exchange_id):
    filename = f"transactions_{exchange_id}.json"
    data = load_json_data(user_id, filename)
    if data is None:
        # Inicializar con una lista vacía si el archivo no existe o está vacío
        save_json_data(user_id, [], filename)
        return []
    return data


def load_json_data(user_id, filename):
    try:
        user_json_directory = os.path.join(json_directory, user_id)
        filepath = os.path.join(user_json_directory, filename)
        if os.path.exists(filepath):
            with open(filepath, 'r') as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
                else:
                    logging.error(f"Usuario {user_id}: El contenido de {filename} no es una lista.")
        else:
            logging.warning(f"Usuario {user_id}: El archivo {filename} no existe. Creándolo vacío.")
            save_json_data(user_id, [], filename)
            return []
    except json.JSONDecodeError:
        logging.error(f"Usuario {user_id}: Archivo JSON corrupto o vacío: {filename}. Reiniciando.")
        save_json_data(user_id, [], filename)
        return []
    except Exception as e:
        logging.error(f"Usuario {user_id}: Error al cargar datos desde {filename}: {str(e)}")
        return []


def save_transaction(user_id, exchange_id, symbol, buy_order, sell_order, commission):
    required_buy_keys = ['id', 'price', 'amount', 'placed_time']
    required_sell_keys = ['id', 'price', 'amount', 'placed_time']

    if not all(key in buy_order for key in required_buy_keys):
        logging.error(f"Usuario {user_id}: buy_order faltante claves en la transacción para {exchange_id}, {symbol}.")
        return

    if not all(key in sell_order for key in required_sell_keys):
        logging.error(f"Usuario {user_id}: sell_order faltante claves en la transacción para {exchange_id}, {symbol}.")
        return

    filename = f"transactions_{exchange_id}.json"
    transactions = load_json_data(user_id, filename) or []

    buy_time = datetime.fromtimestamp(buy_order.get('placed_time', time.time())).isoformat()
    sell_time = datetime.fromtimestamp(sell_order.get('placed_time', time.time())).isoformat()

    pnl = calculate_pnl(user_id, buy_order, sell_order, commission)

    transaction = {
        'symbol': symbol,
        'buy_order_id': buy_order['id'],
        'buy_price': buy_order['price'],
        'buy_amount': buy_order['amount'],
        'buy_time': buy_time,
        'sell_order_id': sell_order['id'],
        'sell_price': sell_order['price'],
        'sell_amount': sell_order['amount'],
        'sell_time': sell_time,
        'commission': commission,
        'status': 'completed',
        'pnl': pnl,
        'timestamp': datetime.now().isoformat()
    }
    transactions.append(transaction)

    try:
        save_json_data(user_id, transactions, filename)
        logging.info(f"Usuario {user_id}: Transacción guardada para {exchange_id}: {transaction}")
        saved_transactions = load_json_data(user_id, filename)
        if saved_transactions and saved_transactions[-1] == transaction:
            logging.info(f"Usuario {user_id}: Verificado: la transacción se guardó correctamente")
        else:
            logging.error(f"Usuario {user_id}: Error: la transacción no se guardó correctamente")
    except Exception as e:
        logging.error(f"Usuario {user_id}: Error al intentar guardar la transacción en {filename}: {str(e)}")

    if exchange_id not in users_profit_loss[user_id]:
        users_profit_loss[user_id][exchange_id] = {}
    if symbol not in users_profit_loss[user_id][exchange_id]:
        users_profit_loss[user_id][exchange_id][symbol] = 0
    users_profit_loss[user_id][exchange_id][symbol] += pnl

    if exchange_id not in users_daily_trades[user_id]:
        users_daily_trades[user_id][exchange_id] = {}
    if symbol not in users_daily_trades[user_id][exchange_id]:
        users_daily_trades[user_id][exchange_id][symbol] = []
    users_daily_trades[user_id][exchange_id][symbol].append(transaction)

    symbol_config = next((s for s in users_symbols_config[user_id] if s["symbol"] == symbol), None)
    if symbol_config and symbol_config.get("strategy") == "compound":
        if pnl > 0:
            if exchange_id not in users_reinvested_profits[user_id]:
                users_reinvested_profits[user_id][exchange_id] = {}
            if symbol not in users_reinvested_profits[user_id][exchange_id]:
                users_reinvested_profits[user_id][exchange_id][symbol] = 0.0

            buy_cost = buy_order['price'] * buy_order['amount']
            if buy_cost > 0:
                profit_percentage = (pnl / buy_cost) * 100
                current_total = users_reinvested_profits[user_id][exchange_id][symbol]
                users_reinvested_profits[user_id][exchange_id][symbol] = current_total + profit_percentage

                logging.info(
                    f"Usuario {user_id}: COMPOUND - Nueva ganancia {profit_percentage:.2f}% => "
                    f"Total acumulado: {users_reinvested_profits[user_id][exchange_id][symbol]:.2f}% "
                    f"para {symbol} en {exchange_id}"
                )
                save_reinvested_profits(user_id)

def initialize_symbol(user_id, exchange_id, symbol):
    """Inicializa todas las estructuras necesarias para un símbolo."""
    # Asegurar que existen todas las estructuras padre
    if user_id not in users_daily_trades:
        users_daily_trades[user_id] = {}
    if user_id not in users_market_prices:
        users_market_prices[user_id] = {}
    if user_id not in users_predicted_prices:
        users_predicted_prices[user_id] = {}
    if user_id not in users_open_orders:
        users_open_orders[user_id] = {}
    if user_id not in users_pending_sells:
        users_pending_sells[user_id] = {}
    if user_id not in users_daily_losses:
        users_daily_losses[user_id] = {}
    if user_id not in users_profit_loss:
        users_profit_loss[user_id] = {}
    if user_id not in users_active_symbols:
        users_active_symbols[user_id] = {}
    if user_id not in users_reactivation_thresholds:
        users_reactivation_thresholds[user_id] = {}
    if user_id not in users_symbol_tasks:
        users_symbol_tasks[user_id] = {}
    if user_id not in users_token_running_status:
        users_token_running_status[user_id] = {}
    if user_id not in users_reinvested_profits:
        users_reinvested_profits[user_id] = {}
    if user_id not in users_order_trackers:
        users_order_trackers[user_id] = OrderTracker()

    # Asegurar que existen las estructuras para el exchange
    for container in [users_daily_trades, users_market_prices, users_predicted_prices,
                     users_open_orders, users_pending_sells, users_daily_losses,
                     users_profit_loss, users_active_symbols, users_reactivation_thresholds,
                     users_symbol_tasks, users_token_running_status, users_reinvested_profits]:
        if exchange_id not in container[user_id]:
            container[user_id][exchange_id] = {}

    # Inicializar el símbolo en cada estructura con valores por defecto
    users_daily_trades[user_id][exchange_id][symbol] = []
    users_market_prices[user_id][exchange_id][symbol] = 0
    users_predicted_prices[user_id][exchange_id][symbol] = 0
    users_open_orders[user_id][exchange_id][symbol] = []
    users_pending_sells[user_id][exchange_id][symbol] = []
    users_daily_losses[user_id][exchange_id][symbol] = 0
    users_profit_loss[user_id][exchange_id][symbol] = 0
    users_active_symbols[user_id][exchange_id][symbol] = True
    users_reactivation_thresholds[user_id][exchange_id][symbol] = None
    users_symbol_tasks[user_id][exchange_id][symbol] = None
    users_token_running_status[user_id][exchange_id][symbol] = False
    users_reinvested_profits[user_id][exchange_id][symbol] = 0.0

    # Asegurar que el OrderTracker tiene las estructuras necesarias
    if exchange_id not in users_order_trackers[user_id].buy_orders:
        users_order_trackers[user_id].buy_orders[exchange_id] = {}
    if exchange_id not in users_order_trackers[user_id].sell_orders:
        users_order_trackers[user_id].sell_orders[exchange_id] = {}
    if symbol not in users_order_trackers[user_id].buy_orders[exchange_id]:
        users_order_trackers[user_id].buy_orders[exchange_id][symbol] = {}
    if symbol not in users_order_trackers[user_id].sell_orders[exchange_id]:
        users_order_trackers[user_id].sell_orders[exchange_id][symbol] = {}

    # Verificar configuración del símbolo
    symbol_config = get_symbol_config(user_id, symbol)
    if symbol_config:
        # Sincronizar estado activo con la configuración
        is_active = symbol_config.get('active_exchanges', {}).get(exchange_id, True)
        users_active_symbols[user_id][exchange_id][symbol] = is_active
        users_token_running_status[user_id][exchange_id][symbol] = False  # Siempre inicia detenido

    logging.info(f"Usuario {user_id}: Estructuras inicializadas para {symbol} en {exchange_id}")

def initialize_active_exchanges(user_id):
    for token in users_symbols_config[user_id]:
        if 'active_exchanges' not in token:
            token['active_exchanges'] = {}
        for exchange_id in token.get('exchanges', []):
            token['active_exchanges'][exchange_id] = True  # Por defecto activo


def migrate_symbols_to_dicts(user_id):
    migration_needed = False

    # Conjunto para rastrear pares únicos (símbolo, exchange)
    unique_pairs = set()

    for exchange_id, exchange in users_exchanges_config[user_id].items():
        for symbol in exchange.get('symbols', []):
            # Verificar si este par ya existe
            pair = (symbol, exchange_id)
            if pair in unique_pairs:
                logging.warning(
                    f"Usuario {user_id}: Detectado duplicado durante migración: {symbol} en {exchange_id}. Ignorando.")
                continue

            unique_pairs.add(pair)

            existing_symbol = next((s for s in users_symbols_config[user_id] if s['symbol'] == symbol), None)
            if existing_symbol:
                if exchange_id not in existing_symbol.get('exchanges', []):
                    existing_symbol['exchanges'].append(exchange_id)
                    existing_symbol.setdefault('active_exchanges', {})[exchange_id] = True
                    migration_needed = True
                    logging.info(
                        f"Usuario '{user_id}': Exchange '{exchange_id}' asociado al símbolo '{symbol}' con estrategia '{existing_symbol['strategy']}'.")
            else:
                new_symbol = {
                    'symbol': symbol,
                    'spread': 0.1,
                    'take_profit': 5,
                    'trade_amount': 0.001,
                    'order_expiration': 60,
                    'daily_loss_max': 100,
                    'reactivation_threshold': None,
                    'strategy': 'strategy1',
                    'exchanges': [exchange_id],
                    'active_exchanges': {exchange_id: True}
                }
                users_symbols_config[user_id].append(new_symbol)
                migration_needed = True
                logging.info(f"Usuario '{user_id}': Nuevo símbolo creado durante la migración: {new_symbol}")
                initialize_symbol(user_id, exchange_id, symbol)

    if migration_needed:
        # Reconstruir las listas de símbolos en cada exchange
        for ex_id in users_exchanges_config[user_id].keys():
            users_exchanges_config[user_id][ex_id]['symbols'] = []

        # Reconstruir basado en tokens únicos
        for token in users_symbols_config[user_id]:
            for ex_id in token.get('exchanges', []):
                if ex_id in users_exchanges_config[user_id]:
                    if token['symbol'] not in users_exchanges_config[user_id][ex_id]['symbols']:
                        users_exchanges_config[user_id][ex_id]['symbols'].append(token['symbol'])

        save_encrypted_config(user_id)
        logging.info(f"Usuario '{user_id}': Migración de símbolos completada.")
    else:
        logging.info(f"Usuario '{user_id}': No se requirió migración de símbolos.")


def initialize_structures(user_id):
    if user_id not in users_exchanges_config:
        users_exchanges_config[user_id] = {}

    # Estructuras que ya tenías
    users_connection_status[user_id] = {
        exchange_id: 'Disconnected'
        for exchange_id in users_exchanges_config[user_id].keys()
    }
    users_exchange_running_status[user_id] = {
        exchange_id: False
        for exchange_id in users_exchanges_config[user_id].keys()
    }

    # AGREGAR ESTA LÍNEA JUSTO DESPUÉS DE LAS INICIALIZACIONES ANTERIORES
    configure_user_limits(user_id)
    
    users_daily_trades[user_id] = {}
    users_market_prices[user_id] = {}
    users_predicted_prices[user_id] = {}
    users_open_orders[user_id] = {}
    users_pending_sells[user_id] = {}
    users_daily_losses[user_id] = {}
    users_profit_loss[user_id] = {}
    users_active_symbols[user_id] = {}
    users_reactivation_thresholds[user_id] = {}
    users_order_trackers[user_id] = OrderTracker()
    users_actions_log[user_id] = deque(maxlen=1000)

    # Aseguramos reinvested_profits y exchange_tasks, etc.
    if user_id not in users_reinvested_profits:
        users_reinvested_profits[user_id] = {}
    users_exchange_tasks[user_id] = {}
    users_first_sell_order_placed[user_id] = False

    # --- NUEVO: inicializar tasks y running_status por símbolo ---
    if user_id not in users_symbol_tasks:
        users_symbol_tasks[user_id] = {}
    if user_id not in users_token_running_status:
        users_token_running_status[user_id] = {}
    # ------------------------------------------------------------

    if user_id not in users_symbols_config:
        users_symbols_config[user_id] = []

    if user_id not in users_exchanges:
        users_exchanges[user_id] = {}

    if user_id not in users_order_trackers:
        users_order_trackers[user_id] = OrderTracker()

    # PRIMERO: Limpiar posibles duplicados en la configuración de símbolos
    clean_token_config(user_id)

    # SEGUNDO: Reconstruir todas las listas de símbolos en cada exchange
    for exchange_id in users_exchanges_config[user_id].keys():
        users_exchanges_config[user_id][exchange_id]['symbols'] = []

    # Reconstruir las listas basadas en symbols_config depurados
    for token in users_symbols_config[user_id]:
        for ex_id in token.get('exchanges', []):
            if ex_id in users_exchanges_config[user_id]:
                if token['symbol'] not in users_exchanges_config[user_id][ex_id]['symbols']:
                    users_exchanges_config[user_id][ex_id]['symbols'].append(token['symbol'])

    # Para cada exchange, inicializar estructuras por símbolo
    for exchange_id, exchange_data in users_exchanges_config[user_id].items():
        exchange_symbols = exchange_data.get('symbols', [])

        # Inicializar diccionarios de datos para cada símbolo
        if exchange_id not in users_daily_trades[user_id]:
            users_daily_trades[user_id][exchange_id] = {}
        if exchange_id not in users_market_prices[user_id]:
            users_market_prices[user_id][exchange_id] = {}
        if exchange_id not in users_predicted_prices[user_id]:
            users_predicted_prices[user_id][exchange_id] = {}
        if exchange_id not in users_open_orders[user_id]:
            users_open_orders[user_id][exchange_id] = {}
        if exchange_id not in users_pending_sells[user_id]:
            users_pending_sells[user_id][exchange_id] = {}
        if exchange_id not in users_daily_losses[user_id]:
            users_daily_losses[user_id][exchange_id] = {}
        if exchange_id not in users_profit_loss[user_id]:
            users_profit_loss[user_id][exchange_id] = {}
        if exchange_id not in users_active_symbols[user_id]:
            users_active_symbols[user_id][exchange_id] = {}
        if exchange_id not in users_reactivation_thresholds[user_id]:
            users_reactivation_thresholds[user_id][exchange_id] = {}
        if exchange_id not in users_symbol_tasks[user_id]:
            users_symbol_tasks[user_id][exchange_id] = {}
        if exchange_id not in users_token_running_status[user_id]:
            users_token_running_status[user_id][exchange_id] = {}

        # Inicializar cada símbolo individual
        for symbol in exchange_symbols:
            if symbol not in users_daily_trades[user_id][exchange_id]:
                users_daily_trades[user_id][exchange_id][symbol] = []
            if symbol not in users_market_prices[user_id][exchange_id]:
                users_market_prices[user_id][exchange_id][symbol] = 0
            if symbol not in users_predicted_prices[user_id][exchange_id]:
                users_predicted_prices[user_id][exchange_id][symbol] = 0
            if symbol not in users_open_orders[user_id][exchange_id]:
                users_open_orders[user_id][exchange_id][symbol] = []
            if symbol not in users_pending_sells[user_id][exchange_id]:
                users_pending_sells[user_id][exchange_id][symbol] = []
            if symbol not in users_daily_losses[user_id][exchange_id]:
                users_daily_losses[user_id][exchange_id][symbol] = 0
            if symbol not in users_profit_loss[user_id][exchange_id]:
                users_profit_loss[user_id][exchange_id][symbol] = 0
            if symbol not in users_active_symbols[user_id][exchange_id]:
                users_active_symbols[user_id][exchange_id][symbol] = True
            if symbol not in users_reactivation_thresholds[user_id][exchange_id]:
                users_reactivation_thresholds[user_id][exchange_id][symbol] = None
            if symbol not in users_symbol_tasks[user_id][exchange_id]:
                users_symbol_tasks[user_id][exchange_id][symbol] = None
            if symbol not in users_token_running_status[user_id][exchange_id]:
                users_token_running_status[user_id][exchange_id][symbol] = False

    logging.info(f"Estructuras inicializadas para el usuario {user_id}")
    # Guardar la configuración limpia
    save_encrypted_config(user_id)


def clean_token_config(user_id):
    """Elimina tokens duplicados y garantiza la integridad de la configuración."""
    if user_id not in users_symbols_config:
        return

    logging.info(f"Usuario {user_id}: Limpiando configuración de tokens...")

    # Rastrear pares únicos (símbolo, exchange)
    token_exchange_pairs = {}  # {(símbolo, exchange): índice_token}
    tokens_to_keep = []

    # Primera pasada: identificar duplicados y tokens válidos
    for token in users_symbols_config[user_id]:
        symbol = token.get('symbol')
        if not symbol:
            continue  # Ignorar tokens sin símbolo

        # Filtrar exchanges para este token
        valid_exchanges = []
        for ex_id in token.get('exchanges', []):
            pair = (symbol, ex_id)

            if pair in token_exchange_pairs:
                # Este es un duplicado, omitir este exchange para este token
                logging.warning(f"Usuario {user_id}: Detectado duplicado: {symbol} en {ex_id}. Ignorando.")
                continue

            token_exchange_pairs[pair] = len(tokens_to_keep)
            valid_exchanges.append(ex_id)

        # Si este token tiene exchanges válidos, conservarlo
        if valid_exchanges:
            # Crear una copia limpia del token
            clean_token = token.copy()
            clean_token['exchanges'] = valid_exchanges
            clean_token['active_exchanges'] = {ex: True for ex in valid_exchanges}
            tokens_to_keep.append(clean_token)

    # Reemplazar la lista de símbolos con la lista depurada
    users_symbols_config[user_id] = tokens_to_keep
    logging.info(f"Usuario {user_id}: Limpieza completada. Se mantuvieron {len(tokens_to_keep)} tokens únicos.")


def initialize_json_files(user_id):
    user_json_directory = os.path.join(json_directory, user_id)
    if not os.path.exists(user_json_directory):
        os.makedirs(user_json_directory)
    for exchange_id in users_exchanges_config[user_id].keys():
        trades_file = f"trades_{exchange_id}.json"
        transactions_file = f"transactions_{exchange_id}.json"
        if not os.path.exists(os.path.join(user_json_directory, trades_file)):
            save_json_data(user_id, [], trades_file)
            logging.info(f"Archivo {trades_file} inicializado para el usuario {user_id}.")
        if not os.path.exists(os.path.join(user_json_directory, transactions_file)):
            save_json_data(user_id, [], transactions_file)
            logging.info(f"Archivo {transactions_file} inicializado para el usuario {user_id}.")
    logging.info(f"Archivos JSON inicializados para todos los exchanges del usuario {user_id}")


def get_exchanges_config(user_id):
    # Devuelve la configuración de exchanges para el usuario
    return users_exchanges_config.get(user_id, {})


def get_exchange_statuses(user_id):
    # Devuelve el estado de los exchanges para el usuario
    return users_exchange_running_status.get(user_id, {})


def get_all_pnl(user_id):
    # Calcula y devuelve el PnL para todos los exchanges del usuario
    pnl = {}
    for exchange_id in users_exchanges_config.get(user_id, {}):
        pnl[exchange_id] = get_total_pnl(user_id, exchange_id)
    return pnl


def get_completed_orders(user_id):
    # Obtiene las últimas 50 órdenes completadas para el usuario
    completed_orders = []
    for exchange_id, exchange in users_exchanges_config.get(user_id, {}).items():
        for symbol, orders in users_order_trackers[user_id].buy_orders.get(exchange_id, {}).items():
            for order_id, order in orders.items():
                if order['status'] == 'completed':
                    completed_orders.append({
                        'exchange_id': exchange_id,
                        'symbol': symbol,
                        'type': 'Compra',
                        'amount': order['amount'],
                        'price': order['price'],
                        'status': order['status']
                    })
        for symbol, orders in users_order_trackers[user_id].sell_orders.get(exchange_id, {}).items():
            for order_id, order in orders.items():
                if order['status'] == 'completed':
                    completed_orders.append({
                        'exchange_id': exchange_id,
                        'symbol': symbol,
                        'type': 'Venta',
                        'amount': order['amount'],
                        'price': order['price'],
                        'status': order['status']
                    })
    return sorted(completed_orders, key=lambda x: x['timestamp'], reverse=True)[:50]


def get_infinity_active_orders(user_id, exchange_id, symbol):
    """Retorna la cantidad de órdenes activas de compra y venta para un token Infinity."""
    active_orders = {"buy": 0, "sell": 0}

    try:
        # Método directo: obtener órdenes abiertas del exchange
        if user_id in users_exchanges and exchange_id in users_exchanges[user_id]:
            exchange = users_exchanges[user_id][exchange_id]
            try:
                # Usar un enfoque más seguro para obtener órdenes
                open_orders = []
                try:
                    import concurrent.futures
                    # Usar run_coroutine_threadsafe con timeout
                    future = asyncio.run_coroutine_threadsafe(
                        exchange.fetch_open_orders(symbol),
                        loop  # Asumiendo que 'loop' es una variable global disponible
                    )
                    # Esperar máximo 2 segundos por los resultados
                    open_orders = future.result(timeout=2)
                except (concurrent.futures.TimeoutError, Exception) as e:
                    logging.error(f"Error obteniendo órdenes para {symbol} en {exchange_id}: {e}")

                for order in open_orders:
                    if order['side'] == 'buy':
                        active_orders["buy"] += 1
                    elif order['side'] == 'sell':
                        active_orders["sell"] += 1
            except Exception as e:
                logging.error(f"Error obteniendo órdenes del exchange: {e}")

        # Método de respaldo: revisar estructuras internas
        if len(open_orders) == 0:
            if user_id in users_order_trackers:
                tracker = users_order_trackers[user_id]
                if exchange_id in tracker.buy_orders and symbol in tracker.buy_orders[exchange_id]:
                    active_orders["buy"] = len(
                        [o for o in tracker.buy_orders[exchange_id][symbol].values() if o['status'] == 'open'])

                if exchange_id in tracker.sell_orders and symbol in tracker.sell_orders[exchange_id]:
                    active_orders["sell"] = len(
                        [o for o in tracker.sell_orders[exchange_id][symbol].values() if o['status'] == 'open'])

    except Exception as e:
        logging.error(f"Error al obtener órdenes activas de Infinity: {e}")

    return active_orders

def get_infinity_roi(user_id, exchange_id, symbol):
    """Calcula el ROI para un token Infinity."""
    try:
        # Limitar el tiempo de ejecución de esta función
        start_time = time.time()
        max_execution_time = 2  # segundos

        # Buscar la configuración del token
        token_config = next((t for t in users_symbols_config[user_id] if t['symbol'] == symbol), None)
        if not token_config:
            return 0

        # Obtener el PnL acumulado
        pnl = users_profit_loss.get(user_id, {}).get(exchange_id, {}).get(symbol, 0)

        # Obtener el capital inicial
        initial_capital = token_config.get('total_balance_usdt', 1000)

        # Verificar tiempo para evitar operaciones largas
        if time.time() - start_time > max_execution_time:
            # Si ya tomó demasiado tiempo, devolver solo el ROI básico
            if initial_capital > 0:
                return (pnl / initial_capital) * 100
            return 0

        # Calcular y retornar el ROI
        if initial_capital > 0:
            roi = (pnl / initial_capital) * 100
            return roi
        return 0
    except Exception as e:
        logging.error(f"Error al calcular ROI de Infinity: {e}")
        return 0

async def place_order_async(user_id, symbol, side, amount, price, exchange_id, retries=3, buy_order_id=None):
    await update_pending_sells(user_id, exchange_id, symbol)

    if not is_exchange_running(user_id, exchange_id):
        return None

    symbol_config = get_symbol_config(user_id, symbol)
    if not symbol_config:
        return None

    # Validar monto y precio iniciales
    if amount <= 0 or price <= 0:
        logging.error(f"Usuario {user_id}: Valores inválidos: amount={amount}, price={price}")
        return None

    # -- Ajustes para la estrategia compound --
    if side == 'buy' and symbol_config.get("strategy") == "compound":
        try:
            # 1) Obtener la configuración compound
            max_reinvestment_pct = symbol_config.get('max_reinvestment_pct', 50.0)
            initial_capital = symbol_config.get('initial_capital', 0)

            accumulated_profit = users_reinvested_profits[user_id].get(exchange_id, {}).get(symbol, 0.0)
            if accumulated_profit > 0:
                # 2) Calcular factor para ajustarse a la reinversión sin pasarse de max_reinvestment_pct
                max_factor = 1 + (max_reinvestment_pct / 100.0)
                factor = min(1 + (accumulated_profit / 100.0), max_factor)

                new_amount = amount * factor
                total_cost = new_amount * price
                max_allowed = initial_capital + (initial_capital * max_reinvestment_pct / 100)

                if total_cost > max_allowed:
                    # Ajustar el amount para no exceder el máximo permitido
                    new_amount = max_allowed / price
                    logging.warning(
                        f"Usuario {user_id}: [compound] Ajustando cantidad para no exceder capital máximo:"
                        f"\n - Cantidad ajustada: {new_amount:.8f}"
                        f"\n - Capital máximo: {max_allowed:.4f}"
                    )

                amount = new_amount
                logging.info(
                    f"Usuario {user_id}: [compound] Ajuste de compra para {symbol}:"
                    f"\n - Ganancia acumulada: {accumulated_profit:.2f}%"
                    f"\n - Factor aplicado: {factor:.4f}"
                    f"\n - Cantidad final: {amount:.8f}"
                )

        except Exception as e:
            logging.error(f"Usuario {user_id}: Error al calcular ajuste compound: {str(e)}")
            return None

        # -- Ajuste para no exceder la SUMA del capital inicial (evitar exceder en órdenes abiertas) --
        open_orders_total = sum(
            o['amount'] * o['price']
            for o in users_open_orders[user_id]
                .get(exchange_id, {})
                .get(symbol, [])
            if o.get('side') == 'buy' and o.get('status') == 'open'
        )
        new_order_total = amount * price
        total_exposure = open_orders_total + new_order_total

        if total_exposure > initial_capital:
            # En lugar de cancelar, reducimos la cantidad de compra para no pasarnos.
            leftover_capital = max(0, initial_capital - open_orders_total)
            if leftover_capital <= 0:
                # No hay nada de capital libre, se podría decidir no comprar.
                logging.warning(
                    f"Usuario {user_id}: No queda capital disponible para {symbol}. Orden no colocada."
                )
                return None
            # Calculamos la cantidad que sí cabe en leftover_capital
            new_amount = leftover_capital / price

            if new_amount <= 0:
                logging.warning(
                    f"Usuario {user_id}: leftover_capital ({leftover_capital:.4f}) insuficiente para comprar {symbol}."
                )
                return None

            logging.info(
                f"Usuario {user_id}: Ajustando amount para no exceder capital inicial. "
                f"Sobran {leftover_capital:.4f} USDT => nueva cantidad = {new_amount:.8f} {symbol}"
            )
            amount = new_amount

    # Verificar si se puede colocar la orden (límites de órdenes abiertas, etc.)
    if not await can_place_order(user_id, exchange_id, symbol, side, symbol_config):
        return None

    # Intentar crear la orden en el exchange
    for attempt in range(retries):
        try:
            order = await create_exchange_order(user_id, exchange_id, symbol, side, amount, price)
            order['price'] = price

            order_info = {
                'id': order['id'],
                'side': side,
                'amount': amount,
                'price': price,
                'status': order['status'],
                'placed_time': time.time(),
                'buy_order_id': buy_order_id
            }

            if side == 'buy':
                users_order_trackers[user_id].add_buy_order(exchange_id, symbol, order['id'], amount, price)
                if exchange_id not in users_open_orders[user_id]:
                    users_open_orders[user_id][exchange_id] = {}
                if symbol not in users_open_orders[user_id][exchange_id]:
                    users_open_orders[user_id][exchange_id][symbol] = []
                order_info = create_order_info(user_id, order['id'], side, amount, price, symbol)
                # Una vez confirmada la colocación exitosa de la orden en el exchange, se actualiza su estado a "open"
                order_info['status'] = 'open'
                users_open_orders[user_id][exchange_id][symbol].append(order_info)


            else:
                users_order_trackers[user_id].add_sell_order(exchange_id, symbol, order['id'], amount, price,
                                                             buy_order_id=None)
                if exchange_id not in users_pending_sells[user_id]:
                    users_pending_sells[user_id][exchange_id] = {}
                if symbol not in users_pending_sells[user_id][exchange_id]:
                    users_pending_sells[user_id][exchange_id][symbol] = []
                order_info = create_order_info(user_id, order['id'], side, amount, price, symbol)
                # Una vez confirmada la colocación exitosa de la orden de venta, se actualiza su estado a "open"
                order_info['status'] = 'open'
                users_pending_sells[user_id][exchange_id][symbol].append(order_info)

            logging.info(
                f"Usuario {user_id}: Orden {side.upper()} colocada: {order['id']} "
                f"para {symbol} en {exchange_id} a {price}"
            )
            return order

        except Exception as e:
            if attempt < retries - 1:
                logging.warning(f"Error en intento {attempt + 1}/{retries}: {str(e)}")
                await asyncio.sleep(2 ** attempt)
            else:
                logging.error(f"Error final después de {retries} intentos: {str(e)}")
                break

    return None


async def place_buy_order_compound(user_id, exchange_id, symbol, amount, price, symbol_config):
    """
    Lógica de compra específica para Compound:
    - Verifica `can_place_order()`.
    - Valida cantidad y precio.
    - Llama a place_order_async(...) con side='buy'.
    """
    try:
        logging.info(f"Usuario {user_id}: Attempting to place compound buy order for {symbol} at {price}")

        # Verificar que amount y price sean positivos
        if amount <= 0 or price <= 0:
            logging.error(f"Usuario {user_id}: Valores inválidos para orden compound: amount={amount}, price={price}")
            return None

        # Verificar si se puede colocar una orden
        can_place = await can_place_order(user_id, exchange_id, symbol, "buy", symbol_config)
        if not can_place:
            logging.warning(
                f"Usuario {user_id}: No se puede colocar BUY compound en {symbol}. Límite de órdenes alcanzado.")
            return None

        # Registrar información detallada antes de colocar la orden
        logging.info(f"Usuario {user_id}: Colocando orden compound: {amount} {symbol} a {price}")

        # Intentar colocar la orden
        buy_order = await place_order_async(
            user_id,
            symbol,
            'buy',
            amount,
            price,
            exchange_id,
            retries=3
        )

        if buy_order:
            logging.info(f"Usuario {user_id}: Orden compound colocada exitosamente: {buy_order['id']}")
        else:
            logging.error(f"Usuario {user_id}: Falló al colocar orden compound para {symbol}")

        return buy_order

    except Exception as e:
        logging.error(f"Usuario {user_id}: Error en place_buy_order_compound: {e}", exc_info=True)
        return None

# NUEVO - espera ejecución de la compra
async def wait_for_buy_execution(user_id, buy_order, exchange_id, symbol, timeout):
    """
    Espera hasta 'timeout' segs la ejecución de la orden de compra.
    Si no se ejecuta en ese lapso, la cancela y retorna None.
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        order_id = buy_order['id']
        order = await users_exchanges[user_id][exchange_id].fetch_order(order_id, symbol)
        if order['status'] == 'closed':
            return order
        elif order['status'] == 'canceled':
            return None
        await asyncio.sleep(5)

    # Timeout: cancelar la orden de compra
    await cancel_order_async(user_id, buy_order['id'], symbol, exchange_id)
    return None


def is_exchange_running(user_id, exchange_id):
    if not users_exchange_running_status[user_id][exchange_id]:
        logging.info(f"Exchange {exchange_id} no está en ejecución para el usuario {user_id}")
        return False
    return True


def get_symbol_config(user_id, symbol):
    mark_user_active(user_id)
    symbol_config = next((s for s in users_symbols_config[user_id] if s['symbol'] == symbol), None)
    if not symbol_config:
        logging.error(f"No se encontró configuración para el símbolo {symbol} del usuario {user_id}")
    return symbol_config

async def can_place_order(user_id, exchange_id, symbol, side, symbol_config):
    try:
        # Obtener órdenes abiertas del exchange
        exchange = users_exchanges[user_id][exchange_id]
        open_orders = await exchange.fetch_open_orders(symbol)

        # Contar órdenes reales del exchange
        num_open_buys = len([order for order in open_orders if order['side'] == 'buy'])
        num_pending_sells = len([order for order in open_orders if order['side'] == 'sell'])

        max_orders = symbol_config['max_orders']
        max_sell_orders = symbol_config['max_sell_orders']

        if side == 'buy':
            logging.info(f"Usuario {user_id}: Órdenes de compra abiertas: {num_open_buys}, Límite: {max_orders}")
            logging.info(
                f"Usuario {user_id}: Órdenes de venta pendientes: {num_pending_sells}, Límite: {max_sell_orders}")

            if num_pending_sells >= max_sell_orders:
                logging.info(f"Usuario {user_id}: Límite de órdenes de venta alcanzado.")
                return False

            if num_open_buys >= max_orders:
                logging.info(f"Usuario {user_id}: Límite de órdenes de compra alcanzado.")
                return False

        elif side == 'sell':
            if num_pending_sells >= max_sell_orders:
                logging.info(f"Usuario {user_id}: Límite de órdenes de venta alcanzado.")
                return False

        return True

    except Exception as e:
        logging.error(f"Usuario {user_id}: Error al verificar órdenes abiertas: {e}")
        return False


async def get_ordered_grid_slots(user_id, exchange_id, symbol, market_price, symbol_config):
    """
    Obtiene el siguiente nivel disponible en la grilla manteniendo spread exacto.
    Retorna una lista con un único nivel - el siguiente disponible en la secuencia.
    """
    try:
        # Validar parámetros de entrada
        if market_price <= 0:
            logging.error(f"Usuario {user_id}: Market price inválido para {symbol}: {market_price}")
            return [market_price * 0.99]  # Fallback seguro

        # Obtener y validar parámetros de configuración
        if 'spread' not in symbol_config or not isinstance(symbol_config['spread'], (int, float)) or symbol_config[
            'spread'] <= 0:
            spread = 0.01  # Default 1%
            logging.warning(f"Usuario {user_id}: Spread inválido para {symbol}, usando 1%")
        else:
            spread = float(symbol_config['spread'])

        if 'max_orders' not in symbol_config or not isinstance(symbol_config['max_orders'], (int)) or symbol_config[
            'max_orders'] <= 0:
            max_orders = 10  # Default 10 órdenes
            logging.warning(f"Usuario {user_id}: max_orders inválido para {symbol}, usando 10")
        else:
            max_orders = int(symbol_config['max_orders'])

        logging.info(
            f"Usuario {user_id}: Calculando grid con spread={spread}, max_orders={max_orders}, market_price={market_price}")

        # 1. Obtener y ordenar órdenes existentes con seguridad
        exchange = users_exchanges[user_id][exchange_id]
        open_orders = await exchange.fetch_open_orders(symbol)

        buy_orders = []
        for order in open_orders:
            if isinstance(order, dict) and order.get('side') == 'buy':
                buy_orders.append(order)

        buy_orders.sort(key=lambda x: x.get('price', 0), reverse=True)
        existing_prices = [order.get('price', 0) for order in buy_orders if order.get('price', 0) > 0]

        logging.info(f"Usuario {user_id}: Órdenes de compra existentes: {len(buy_orders)}, Precios: {existing_prices}")

        # 2. Calcular niveles teóricos con spread exacto
        theoretical_levels = []
        for i in range(max_orders):
            if i == 0:
                # Primer nivel exactamente a un spread bajo el mercado
                level_price = market_price * (1 - spread)
            else:
                # Cada siguiente nivel exactamente a un spread del anterior
                level_price = theoretical_levels[-1] * (1 - spread)
            theoretical_levels.append(level_price)

        logging.info(f"Usuario {user_id}: Niveles teóricos calculados: {theoretical_levels[:3]}...")

        # 3. Si no hay órdenes existentes, retornar el primer nivel
        if not buy_orders:
            logging.info(
                f"Usuario {user_id}: No hay órdenes existentes, retornando primer nivel: {theoretical_levels[0]}")
            return [theoretical_levels[0]]

        # 4. Encontrar primer nivel disponible que respete el spread
        for level in theoretical_levels:
            is_valid = True
            for price in existing_prices:
                if price <= 0:
                    continue
                diff_pct = abs(price - level) / price
                if diff_pct < spread:  # Debe respetar el spread exacto
                    is_valid = False
                    logging.info(
                        f"Usuario {user_id}: Nivel {level} demasiado cercano a precio existente {price}, diff={diff_pct}")
                    break

            if is_valid:
                logging.info(f"Usuario {user_id}: Encontrado nivel válido: {level:.8f} USDT")
                return [level]

        # 5. Si no hay niveles válidos, crear uno seguro
        safe_level = market_price * (1 - spread * 1.1)  # Ligeramente mayor spread
        logging.warning(
            f"Usuario {user_id}: No se encontraron niveles disponibles con spread exacto. Usando nivel seguro: {safe_level}")
        return [safe_level]

    except Exception as e:
        logging.error(f"Usuario {user_id}: Error al calcular slots de grilla: {e}", exc_info=True)
        # Retornar un nivel seguro en caso de error
        return [market_price * 0.99]

async def create_exchange_order(user_id, exchange_id, symbol, side, amount, price):
    exchange = users_exchanges[user_id][exchange_id]
    order = await exchange.create_order(symbol, 'limit', side, amount, price)
    logging.info(f"Usuario {user_id}: Orden {side} colocada exitosamente en {exchange_id}: {order}")
    return order


async def process_placed_order(user_id, order, exchange_id, symbol, side, amount, price, symbol_config):
    # Crear trade_record con status 'open' inicialmente
    trade_record = create_trade_record(exchange_id, symbol, side, amount, price, order['id'], status='open')

    if side == 'buy':
        # Asegurar que las estructuras existen
        if exchange_id not in users_open_orders[user_id]:
            users_open_orders[user_id][exchange_id] = {}
        if symbol not in users_open_orders[user_id][exchange_id]:
            users_open_orders[user_id][exchange_id][symbol] = []

        # Agregar la orden de compra abierta
        users_open_orders[user_id][exchange_id][symbol].append(
            create_order_info(
                user_id,
                order['id'],
                side,
                amount,
                price,
                symbol  # <-- SE AGREGA AQUÍ
            )
        )

        users_order_trackers[user_id].add_buy_order(exchange_id, symbol, order['id'], amount, price)
        logging.info(f"Usuario {user_id}: Orden de compra registrada: {order['id']} para {symbol}.")

        # Esperar la ejecución de la orden con timeout
        executed_order = await wait_for_order_execution(user_id, order['id'], symbol, exchange_id,
                                                        timeout=symbol_config['order_expiration'] * 60)
        if executed_order:
            logging.info(f"Usuario {user_id}: Compra ejecutada, colocando orden de venta.")
            # Actualizar el status a 'closed' ya que la orden fue ejecutada
            trade_record['status'] = 'closed'
            save_trade(user_id, trade_record, exchange_id)

            sell_order = await place_sell_order_until_placed(
                user_id,
                exchange_id,
                symbol,
                executed_order['filled'],
                executed_order['price'],
                symbol_config,
                buy_order_id=order['id']
            )

            if sell_order:
                # Actualizar el estado de la orden de compra a 'closed'
                users_order_trackers[user_id].update_order_status(exchange_id, symbol, order['id'], 'closed',
                                                                  is_buy=True)
                logging.info(
                    f"Usuario {user_id}: Orden de venta {sell_order['id']} colocada exitosamente para la compra {order['id']}")
            else:
                logging.error(
                    f"Usuario {user_id}: No se pudo colocar la orden de venta para la compra {order['id']} después de varios intentos.")

            # Actualizar users_daily_trades si es necesario
            save_trade(user_id, trade_record, exchange_id)
        else:
            logging.info(f"Usuario {user_id}: La orden de compra {order['id']} no se ejecutó a tiempo. Cancelando.")
            # Cancelar la orden de compra si no se ejecutó a tiempo
            await cancel_order_async(user_id, order['id'], symbol, exchange_id)
            # Actualizar el estado de la orden a 'canceled'
            users_order_trackers[user_id].update_order_status(exchange_id, symbol, order['id'], 'canceled', is_buy=True)
            # Remover la orden de compra de las órdenes abiertas
            remove_buy_order(user_id, exchange_id, symbol, order['id'])

    elif side == 'sell':
        # Asegurar que las estructuras existen

        if exchange_id not in users_pending_sells[user_id]:
            users_pending_sells[user_id][exchange_id] = {}
        if symbol not in users_pending_sells[user_id][exchange_id]:
            users_pending_sells[user_id][exchange_id][symbol] = []

    # Crear la orden de venta con estado "pending" inicialmente
        order_info = create_order_info(user_id, order['id'], side, amount, price, symbol)

    # Una vez que se confirma que la orden se colocó correctamente, actualizamos su estado a "open"
        order_info['status'] = 'open'
        users_pending_sells[user_id][exchange_id][symbol].append(order_info)
        users_order_trackers[user_id].add_sell_order(exchange_id, symbol, order['id'], amount, price,
                                                 order.get('buy_order_id'))
        logging.debug(f"Usuario {user_id}: Orden de venta añadida a pending_sells. Total: {len(users_pending_sells[user_id][exchange_id][symbol])}"
    )

        # Encontrar la orden de compra correspondiente
        buy_order = find_matching_buy_order(user_id, exchange_id, symbol, order.get('buy_order_id'))
        if buy_order:
            # Obtener la comisión usando order
            commission = await get_commission(
                user_id,
                exchange_id,
                symbol,
                order['amount'],  # antes usaba sell_order['amount']
                order['price']  # antes usaba sell_order['price']
            )

            sell_order_info = {
                "id": order["id"],
                "symbol": symbol,  # <--- Asegúrate de incluirlo
                "price": order["price"],
                "amount": order["amount"],
                "placed_time": order.get("timestamp", time.time() * 1000) / 1000,
                "side": "sell",  # <--- Por si en save_transaction exiges 'side'
            }

            pnl_value = calculate_pnl(user_id, buy_order, sell_order_info, commission)
            sell_order_info['pnl'] = pnl_value

            # Guardar la transacción completa
            save_transaction(user_id, exchange_id, symbol, buy_order, sell_order_info, commission)

            # Actualizar el estado de la orden de venta a 'completed'
            users_order_trackers[user_id].update_order_status(exchange_id, symbol, order['id'], 'completed',
                                                              is_buy=False)

            # Remover la orden de venta de pending_sells
            users_pending_sells[user_id][exchange_id][symbol].remove(order)
        else:
            logging.error(
                f"Usuario {user_id}: No se encontró una orden de compra correspondiente para la venta {order['id']}.")


def create_trade_record(exchange_id, symbol, side, amount, price, order_id, status='open'):
    return {
        'timestamp': datetime.now().isoformat(),
        'exchange': exchange_id,
        'symbol': symbol,
        'side': side,
        'amount': amount,
        'price': price,
        'order_id': order_id,
        'status': 'open',
        'type': 'limit'
    }

def create_order_info(user_id, order_id, side, amount, price, symbol):
    # Inicialmente, la orden se marca como "pending"
    return {
        'id': order_id,
        'user_id': user_id,
        'placed_time': time.time(),
        'side': side,
        'amount': amount,
        'price': price,
        'symbol': symbol,
        'status': 'pending'
    }


async def place_corresponding_sell_order(user_id, exchange_id, symbol, amount, buy_price, symbol_config,
                                         buy_order_id=None):
    """
    Coloca la orden de venta para un símbolo determinado.
    Ahora, SOLO si la estrategia es 'compound' Y es la PRIMERA venta,
    aplicamos el factor 0.9985 (reducción del 0.15%).
    En el resto de los casos, se vende el 'amount' íntegro.
    """
    # Calcula el precio de venta final según 'take_profit'
    sell_price = buy_price * (1 + symbol_config['take_profit'])

    # Verificar si la estrategia es compound y si aún no se ha colocado ninguna venta
    # (usamos la variable users_first_sell_order_placed[user_id], que en tu código
    #   ya se emplea para marcar la primera venta).
    if symbol_config.get("strategy") == "compound" and not users_first_sell_order_placed.get(user_id, False):
        adjusted_amount = amount * 0.9985  # Reducir en 0.15% la primera venta
        users_first_sell_order_placed[user_id] = True
        logging.info(
            f"Usuario {user_id}: (compound) Primera venta: aplicando reducción del 0.15%. Cantidad final: {adjusted_amount}")
    else:
        adjusted_amount = amount

    # Intentar colocar la orden de venta en el exchange
    logging.info(f"Usuario {user_id}: Colocando orden de venta para {symbol} en {sell_price} USDT.")
    sell_order = await place_order_async(
        user_id,
        symbol,
        'sell',
        adjusted_amount,
        sell_price,
        exchange_id,
        buy_order_id=buy_order_id
    )

    if sell_order:
        logging.info(
            f"Usuario {user_id}: Orden de venta {sell_order['id']} colocada para {symbol} "
            f"en {exchange_id} a {sell_price} USDT."
        )
        return sell_order
    else:
        logging.error(f"Usuario {user_id}: No se pudo colocar la orden de venta para {symbol} en {exchange_id}")
        return None


async def place_sell_order_until_placed(
        user_id,
        exchange_id,
        symbol,
        amount,
        buy_price,
        symbol_config,
        buy_order_id=None
):
    attempt = 0
    while users_exchange_running_status[user_id].get(exchange_id, False):
        attempt += 1
        sell_order = await place_corresponding_sell_order(
            user_id,
            exchange_id,
            symbol,
            amount,
            buy_price,
            symbol_config,
            buy_order_id=buy_order_id
        )
        if sell_order:
            logging.info(
                f"Usuario {user_id}: Orden de venta {sell_order['id']} colocada exitosamente (intento {attempt})."
            )
            return sell_order
        logging.warning(
            f"Usuario {user_id}: Falló intento {attempt} en SELL {symbol} (exchange={exchange_id}). "
            "Reintento en 5 segundos..."
        )
        await asyncio.sleep(5)

    logging.error(
        f"Usuario {user_id}: Exchange {exchange_id} se detuvo o inactivo, no se pudo colocar la orden SELL de {symbol}."
    )
    return None


async def audit_orders(user_id, exchange_id, symbol, symbol_config):
    open_buy_orders = users_order_trackers[user_id].get_open_buy_orders(exchange_id, symbol)
    open_sell_orders = users_order_trackers[user_id].get_open_sell_orders(exchange_id, symbol)
    exchange = users_exchanges[user_id][exchange_id]

    # --- AUDITAR ÓRDENES DE COMPRA ---
    for buy_order_id, buy_order in list(open_buy_orders.items()):
        exchange_order = await exchange.fetch_order(buy_order_id, symbol)

        if exchange_order['status'] == 'closed':
            logging.info(
                f"Usuario {user_id}: Orden de compra {buy_order_id} ejecutada. Verificando venta correspondiente."
            )
            # Verificar si ya hay una venta asociada a esta compra
            if any(sell.get('buy_order_id') == buy_order_id for sell in open_sell_orders.values()):
                logging.warning(
                    f"Usuario {user_id}: Ya existe una orden de venta para la compra {buy_order_id}. No se coloca otra."
                )
            else:
                # No existe venta para esta compra: colocar venta
                sell_order = await place_corresponding_sell_order(
                    user_id,
                    exchange_id,
                    symbol,
                    exchange_order['filled'],
                    exchange_order['price'],
                    symbol_config,
                    buy_order_id=buy_order_id
                )
                if sell_order:
                    # Marcar compra como cerrada en el tracker
                    users_order_trackers[user_id].update_order_status(
                        exchange_id, symbol, buy_order_id, 'closed', is_buy=True
                    )
                    # Registrar la nueva venta
                    users_order_trackers[user_id].add_sell_order(
                        exchange_id, symbol, sell_order['id'],
                        exchange_order['filled'], sell_order['price'],
                        buy_order_id
                    )
                    # Guardar la transacción de la compra
                    commission_rate = users_commission_rate[user_id]
                    save_transaction(user_id, exchange_id, symbol, buy_order, sell_order, commission_rate)
                else:
                    logging.error(
                        f"Usuario {user_id}: No se pudo colocar venta para la compra {buy_order_id}."
                    )

            # **ELIMINAR LA ORDEN DE COMPRA DE LA LISTA LOCAL**
            remove_buy_order(user_id, exchange_id, symbol, buy_order_id)

        elif exchange_order['status'] == 'canceled':
            # Marcar la orden de compra como 'canceled'
            users_order_trackers[user_id].update_order_status(
                exchange_id, symbol, buy_order_id, 'canceled', is_buy=True
            )
            # **REMOVERLA DE LA LISTA LOCAL PARA NO CONTARLA COMO ABIERTA**
            remove_buy_order(user_id, exchange_id, symbol, buy_order_id)

    # --- AUDITAR ÓRDENES DE VENTA ---
    for sell_order_id, sell_order in list(open_sell_orders.items()):
        exchange_order = await exchange.fetch_order(sell_order_id, symbol)

        if exchange_order['status'] == 'closed':
            users_order_trackers[user_id].update_order_status(
                exchange_id, symbol, sell_order_id, 'closed', is_buy=False
            )
            logging.info(
                f"Usuario {user_id}: Orden de venta {sell_order_id} ejecutada. Actualizando transacción."
            )
            # Guardar la transacción de venta
            buy_order = users_order_trackers[user_id].buy_orders[exchange_id][symbol].get(sell_order['buy_order_id'])
            if buy_order:
                commission_rate = users_commission_rate[user_id]
                save_transaction(user_id, exchange_id, symbol, buy_order, sell_order, commission_rate)

            # Remover la orden de compra asociada de la lista local
            remove_buy_order(user_id, exchange_id, symbol, buy_order['id'])

        elif exchange_order['status'] == 'canceled':
            logging.warning(
                f"Usuario {user_id}: Orden de venta {sell_order_id} cancelada. Recolocando venta."
            )
            # Reintentar colocar una nueva venta
            new_sell_order = await place_corresponding_sell_order(
                user_id, exchange_id, symbol,
                sell_order['amount'], sell_order['price'],
                symbol_config
            )
            if new_sell_order:
                users_order_trackers[user_id].update_order_status(
                    exchange_id, symbol, sell_order_id, 'canceled', is_buy=False
                )
                users_order_trackers[user_id].add_sell_order(
                    exchange_id, symbol, new_sell_order['id'],
                    sell_order['amount'], new_sell_order['price'],
                    sell_order['buy_order_id']
                )
            # Si falla, quedará pendiente manejarlo manualmente.


async def sync_order_states(user_id, exchange_id, symbol):
    try:
        exchange = users_exchanges[user_id][exchange_id]

        # Obtener órdenes reales del exchange
        exchange_orders = await exchange.fetch_open_orders(symbol)
        exchange_order_ids = {order['id'] for order in exchange_orders}

        # Sincronizar buy orders
        buy_orders = users_order_trackers[user_id].get_open_buy_orders(exchange_id, symbol)
        for order_id, order in list(buy_orders.items()):
            if order_id not in exchange_order_ids:
                # La orden ya no existe en el exchange
                users_order_trackers[user_id].update_order_status(
                    exchange_id, symbol, order_id, 'closed', is_buy=True
                )
                # Remover de open_orders
                users_open_orders[user_id][exchange_id][symbol] = [
                    o for o in users_open_orders[user_id][exchange_id][symbol]
                    if o['id'] != order_id
                ]

        # Sincronizar sell orders
        sell_orders = users_order_trackers[user_id].get_open_sell_orders(exchange_id, symbol)
        for order_id, order in list(sell_orders.items()):
            if order_id not in exchange_order_ids:
                # La orden ya no existe en el exchange
                users_order_trackers[user_id].update_order_status(
                    exchange_id, symbol, order_id, 'closed', is_buy=False
                )
                # Remover de pending_sells
                users_pending_sells[user_id][exchange_id][symbol] = [
                    o for o in users_pending_sells[user_id][exchange_id][symbol]
                    if o['id'] != order_id
                ]

        logging.info(f"Estados sincronizados para {symbol} en {exchange_id}")

    except Exception as e:
        logging.error(f"Error en sync_order_states: {str(e)}")

async def process_sell_order(user_id, exchange_id, symbol, buy_order_id, sell_order):
    buy_order = find_matching_buy_order(user_id, exchange_id, symbol, buy_order_id)
    if not buy_order:
        logging.error(f"Usuario {user_id}: No se encontró la orden de compra {buy_order_id}")
        return

    # Validar precio y cantidad de las órdenes
    if buy_order['price'] <= 0 or buy_order['amount'] <= 0:
        logging.error(f"Usuario {user_id}: Valores inválidos en buy_order: price={buy_order['price']}, amount={buy_order['amount']}")
        return
    if sell_order['price'] <= 0 or sell_order['amount'] <= 0:
        logging.error(f"Usuario {user_id}: Valores inválidos en sell_order: price={sell_order['price']}, amount={sell_order['amount']}")
        return

    try:
        commission = await get_commission(
            user_id,
            exchange_id,
            symbol,
            sell_order['amount'],
            sell_order['price']
        )

        sell_order_info = {
            'id': sell_order['id'],
            'symbol': symbol,
            'price': sell_order['price'],
            'amount': sell_order['amount'],
            'placed_time': sell_order.get('timestamp', time.time() * 1000) / 1000
        }

        # Calcular PNL y manejar ganancias compound
        symbol_config = get_symbol_config(user_id, symbol)
        pnl = 0  # Inicializar pnl fuera del bloque try

        if symbol_config and symbol_config.get("strategy") == "compound":
            try:
                # Validar datos de entrada
                if not all(key in buy_order for key in ['price', 'amount']):
                    raise ValueError("Datos incompletos en buy_order")
                if not all(key in sell_order for key in ['price', 'amount']):
                    raise ValueError("Datos incompletos en sell_order")

                # Calcular PNL con validaciones
                buy_cost = buy_order['price'] * buy_order['amount']
                if buy_cost <= 0:
                    raise ValueError(f"Buy cost inválido: {buy_cost}")

                sell_revenue = sell_order['price'] * sell_order['amount']
                if sell_revenue <= 0:
                    raise ValueError(f"Sell revenue inválido: {sell_revenue}")

                pnl = sell_revenue - buy_cost - commission

                if pnl > 0:
                    # Validar configuración
                    max_reinvestment_pct = symbol_config.get('max_reinvestment_pct', 50.0)
                    if not isinstance(max_reinvestment_pct, (int, float)) or max_reinvestment_pct <= 0:
                        raise ValueError(f"max_reinvestment_pct inválido: {max_reinvestment_pct}")

                    reinvestment_pct = symbol_config.get('reinvestment_percentage', 75.0)
                    if not isinstance(reinvestment_pct, (int, float)) or reinvestment_pct <= 0:
                        raise ValueError(f"reinvestment_percentage inválido: {reinvestment_pct}")

                    # Calcular porcentaje de ganancia
                    profit_percentage = (pnl / buy_cost) * 100

                    # Inicializar estructuras
                    if user_id not in users_reinvested_profits:
                        users_reinvested_profits[user_id] = {}
                    if exchange_id not in users_reinvested_profits[user_id]:
                        users_reinvested_profits[user_id][exchange_id] = {}
                    if symbol not in users_reinvested_profits[user_id][exchange_id]:
                        users_reinvested_profits[user_id][exchange_id][symbol] = 0.0

                    # Calcular reinversión con límites
                    reinvestment_amount = profit_percentage * (reinvestment_pct / 100)
                    current_total = users_reinvested_profits[user_id][exchange_id][symbol]

                    # Aplicar límite máximo
                    if current_total + reinvestment_amount > max_reinvestment_pct:
                        reinvestment_amount = max(0, max_reinvestment_pct - current_total)
                        logging.info(
                            f"Usuario {user_id}: [COMPOUND] Ajustando reinversión al límite máximo "
                            f"({max_reinvestment_pct}%)"
                        )

                    # Actualizar ganancias
                    users_reinvested_profits[user_id][exchange_id][symbol] += reinvestment_amount

                    logging.info(
                        f"Usuario {user_id}: [COMPOUND] Operación completada para {symbol}:"
                        f"\n - Capital inicial: {buy_cost:.4f} USDT"
                        f"\n - Ingreso venta: {sell_revenue:.4f} USDT"
                        f"\n - Comisión: {commission:.4f} USDT"
                        f"\n - PNL: {pnl:.4f} USDT ({profit_percentage:.2f}%)"
                        f"\n - Ganancia reinvertida: {reinvestment_amount:.2f}%"
                        f"\n - Total acumulado: {users_reinvested_profits[user_id][exchange_id][symbol]:.2f}%"
                        f"\n - Límite máximo: {max_reinvestment_pct:.2f}%"
                    )
                    save_reinvested_profits(user_id)

            except Exception as e:
                logging.error(f"Usuario {user_id}: Error procesando ganancia compound: {str(e)}")
                # No reseteamos pnl aquí, usamos el valor calculado o 0 inicial

        # Procesar la transacción
        save_transaction(user_id, exchange_id, symbol, buy_order, sell_order_info, commission)
        remove_buy_order(user_id, exchange_id, symbol, buy_order['id'])

        # Actualizar estado de la orden
        users_order_trackers[user_id].update_order_status(
            exchange_id,
            symbol,
            sell_order['id'],
            'completed',
            is_buy=False
        )

        # Limpiar orden de venta pendiente
        users_pending_sells[user_id][exchange_id][symbol] = [
            order for order in users_pending_sells[user_id][exchange_id][symbol]
            if order['id'] != sell_order['id']
        ]

        logging.info(
            f"Usuario {user_id}: Orden de venta {sell_order['id']} procesada para {symbol} en {exchange_id}:"
            f"\n - Precio compra: {buy_order['price']}"
            f"\n - Precio venta: {sell_order['price']}"
            f"\n - PNL: {pnl:.8f} USDT"
            f"\n - Órdenes de venta pendientes: {len(users_pending_sells[user_id][exchange_id][symbol])}"
        )

    except Exception as e:
        logging.error(f"Usuario {user_id}: Error general procesando orden de venta: {str(e)}")

def handle_network_error(user_id, e, side, symbol, exchange_id, attempt, retries):
    logging.warning(f"Usuario {user_id}: Error de red al colocar la orden {side} para {symbol} en {exchange_id}: {e}")
    if attempt < retries - 1:
        wait_time = 2 ** attempt
        logging.info(f"Usuario {user_id}: Reintentando en {wait_time} segundos...")
        time.sleep(wait_time)


def handle_exchange_error(user_id, e, side, symbol, exchange_id):
    logging.error(
        f"Usuario {user_id}: Error del exchange al colocar la orden {side} para {symbol} en {exchange_id}: {e}")


def handle_unexpected_error(user_id, e, side, symbol, exchange_id):
    logging.error(f"Usuario {user_id}: Error inesperado al colocar la orden {side} para {symbol} en {exchange_id}: {e}")


class InfinityStrategy:
    def __init__(self, exchange, symbol, total_balance_usdt, grid_interval, min_price,
                 check_interval=5, commission=0.001, reinvestment_percentage=75.0,
                 max_reinvestment_pct=50.0, reserve_percentage=20.0, user_id=None):
        self.exchange = exchange
        self.symbol = symbol.strip().upper()
        self.user_id = user_id
        self.total_balance_usdt = total_balance_usdt
        self.grid_interval = grid_interval
        self.initial_min_price = min_price
        self.current_min_price = min_price
        self.check_interval = check_interval
        self.grid_orders = {}
        self.base_price = None
        self.last_base_price = None
        self.allocated_usdt = None
        self.total_allocated_capital = 0  # Nuevo: para rastrear capital total usado
        self.max_grid_levels = None  # Nuevo: para mantener consistente el número de niveles
        self.running = True
        self.commission = commission
        self.price_threshold = 0.015
        self.total_profit = 0.0
        self.reinvested_amount = 0.0
        self.reinvestment_percentage = reinvestment_percentage
        self.max_reinvestment_pct = max_reinvestment_pct
        self.reserve_percentage = reserve_percentage
        self.last_audit_time = 0
        self.audit_interval = 300
        self.user_id = user_id
        self.has_moved_up = False  # <-- NUEVA BANDERA

    async def _retry(self, func, *args, retries=3, initial_delay=1, **kwargs):
        delay = initial_delay
        for attempt in range(1, retries + 1):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                error_msg = str(e).lower()
                if "rate limit" in error_msg or "too many requests" in error_msg:
                    logging.warning(
                        f"InfinityStrategy: Error de rate limit en {func.__name__} (intento {attempt}). Esperando {delay} segundos.")
                else:
                    logging.warning(
                        f"InfinityStrategy: Error en {func.__name__} (intento {attempt}): {e}. Reintentando en {delay} segundos.")
                if attempt == retries:
                    logging.error(f"InfinityStrategy: Se alcanzaron los reintentos máximos en {func.__name__}.")
                    raise
                await asyncio.sleep(delay)
                delay *= 2

    async def get_ticker(self, retries=3, initial_delay=1):
        async def _do_fetch_ticker():
            return await self.exchange.fetch_ticker(self.symbol)

        try:
            return await self._retry(_do_fetch_ticker, retries=retries, initial_delay=initial_delay)
        except Exception as e:
            logging.error(f"InfinityStrategy: No se pudo obtener el ticker tras los reintentos: {e}")
            return None

    async def place_order(self, side, price, amount, retries=3, initial_delay=1):
        async def _do_create_order():
            return await self.exchange.create_order(self.symbol, 'limit', side, amount, price)

        try:
            return await self._retry(_do_create_order, retries=retries, initial_delay=initial_delay)
        except Exception as e:
            logging.error(f"InfinityStrategy: Falló al colocar orden {side} en {price} tras los reintentos: {e}")
            return None

    async def cancel_order(self, order_id, retries=3, initial_delay=1):
        async def _do_cancel_order():
            return await self.exchange.cancel_order(order_id, self.symbol)

        try:
            return await self._retry(_do_cancel_order, retries=retries, initial_delay=initial_delay)
        except Exception as e:
            logging.error(f"InfinityStrategy: Falló al cancelar la orden {order_id} tras los reintentos: {e}")
            return None

    def calculate_grid_allocation(self, n_levels):
        # Calcular el capital total disponible
        available_capital = self.total_balance_usdt * (1 - self.reserve_percentage / 100)

        # Dividir en cantidades exactamente iguales
        per_level = available_capital / n_levels

        # Verificar si estamos usando OKX, que tiene requisitos mínimos más estrictos
        if 'okx' in self.exchange.id.lower():
            # Asegurar mínimo de 5 USDT por nivel (mínimo común en OKX)
            if per_level < 2.01:  # Usar 5.01 para asegurar que esté por encima de 5 incluso con redondeos
                logging.warning(
                    f"InfinityStrategy: Ajustando capital mínimo por nivel de {per_level:.4f} a 5.01 USDT para cumplir requisitos de OKX")
                per_level = 2.01

        # Redondear a un número fijo de decimales DESPUÉS de verificar mínimos
        per_level = round(per_level, 4)

        return per_level
    def process_profit(self, profit):
        self.total_profit += profit
        base_capital = self.total_balance_usdt * (1 - self.reserve_percentage / 100)
        max_reinvestment = base_capital * (self.max_reinvestment_pct / 100)
        max_allowed_capital = base_capital + max_reinvestment

        # Si ya hemos alcanzado el capital máximo, no reinvertir más
        if self.reinvested_amount >= max_reinvestment:
            return 0

        reinvestible = min(profit * (self.reinvestment_percentage / 100), max_reinvestment - self.reinvested_amount)
        self.reinvested_amount += reinvestible

        logging.info(f"InfinityStrategy: Ganancia procesada: {profit:.4f}, Reinvertible: {reinvestible:.4f}, "
                     f"Total reinvertido: {self.reinvested_amount:.4f}/{max_reinvestment:.4f}")

        return reinvestible

    async def initialize_grid(self, preserved_allocations=None):
        logging.info("InfinityStrategy: Inicializando grilla (órdenes BUY)...")
        ticker = await self.get_ticker()
        if ticker is None:
            logging.error("InfinityStrategy: Falló al obtener el ticker. Abortando inicialización de la grilla.")
            return False
        self.base_price = ticker['last']
        self.last_base_price = self.base_price

        # AGREGAR: Limpiar órdenes antiguas antes de crear nuevas
        if preserved_allocations:
            # Antes de colocar nuevas órdenes con capital preservado, cancelar órdenes anteriores
            for order_id in list(self.grid_orders.keys()):
                if self.grid_orders[order_id]["side"] == "buy":
                    await self.cancel_order(order_id)
                    self.grid_orders.pop(order_id, None)
                    logging.info(f"InfinityStrategy: Orden antigua {order_id} cancelada para recalibración")

            # Importante: resetear el total_allocated_capital para que coincida exactamente
            self.total_allocated_capital = sum(preserved_allocations)
            logging.info(f"InfinityStrategy: Capital total reseteado a: {self.total_allocated_capital:.4f} USDT")

        # Obtener órdenes existentes para verificación
        existing_orders = await self.exchange.fetch_open_orders(self.symbol)
        existing_buy_orders = [order for order in existing_orders if order['side'] == 'buy']
        existing_buy_prices = [order['price'] for order in existing_buy_orders]

        # Calcular todos los niveles teóricos
        theoretical_buy_levels = []
        level = 1
        while True:
            buy_price = round(self.base_price * (1 - level * self.grid_interval), 4)
            if buy_price < self.current_min_price:
                break
            theoretical_buy_levels.append(buy_price)
            level += 1

        n_buy = len(theoretical_buy_levels)
        if n_buy == 0:
            logging.error("InfinityStrategy: No se pueden colocar órdenes BUY. Verifica min_price y el precio base.")
            return False

        # Guardar el número máximo de niveles para mantenerlo constante
        if self.max_grid_levels is None:
            self.max_grid_levels = n_buy
        else:
            # Limitar a los niveles originales
            n_buy = min(n_buy, self.max_grid_levels)
            theoretical_buy_levels = theoretical_buy_levels[:n_buy]

        # Identificar qué niveles necesitan órdenes nuevas
        buy_prices = []
        for price in theoretical_buy_levels:
            # Verificar si ya existe una orden en este nivel
            if not any(abs(existing_price - price) / price < 0.0001 for existing_price in existing_buy_prices):
                buy_prices.append(price)

        if not buy_prices:
            logging.info(
                "InfinityStrategy: Todos los niveles de la grilla ya tienen órdenes. No se necesitan nuevas órdenes.")
            return True

        # Gestión de preservación del capital exacto
        total_preserved_capital = 0
        if preserved_allocations:
            # Calcular capital total preservado
            total_preserved_capital = sum(preserved_allocations)

            # Ajustar las asignaciones al número actual de niveles que faltan
            per_level = total_preserved_capital / len(buy_prices)
            allocations = [per_level] * len(buy_prices)

            logging.info(f"InfinityStrategy: Capital total preservado: {total_preserved_capital:.4f} USDT")
        else:
            # Primera inicialización: calcular basado en parámetros
            self.allocated_usdt = self.calculate_grid_allocation(len(buy_prices))
            allocations = [self.allocated_usdt] * len(buy_prices)
            total_preserved_capital = sum(allocations)

        # Guardar el capital total asignado para verificaciones futuras
        if not hasattr(self, 'total_allocated_capital') or self.total_allocated_capital is None:
            self.total_allocated_capital = total_preserved_capital

        # Verificar que no excedemos el capital máximo permitido
        max_allowed_capital = self.total_balance_usdt * (1 - self.reserve_percentage / 100)
        if total_preserved_capital > max_allowed_capital:
            logging.warning(
                f"InfinityStrategy: Capital a utilizar ({total_preserved_capital:.4f}) excede el máximo permitido ({max_allowed_capital:.4f})")
            factor = max_allowed_capital / total_preserved_capital
            allocations = [a * factor for a in allocations]
            total_preserved_capital = sum(allocations)
            logging.info(f"InfinityStrategy: Capital ajustado a {total_preserved_capital:.4f} USDT")

        logging.info(f"InfinityStrategy: Colocando {len(buy_prices)} órdenes BUY faltantes de {n_buy} niveles totales")
        logging.info(f"InfinityStrategy: Capital total a utilizar: {sum(allocations):.4f} USDT")

        # Verificar el capital total
        current_allocated = 0

        for i, (buy_price, allocation) in enumerate(zip(buy_prices, allocations), start=1):
            token_qty = round(allocation / buy_price, 8)
            current_allocated += allocation

            logging.info(
                f"InfinityStrategy: Colocando orden BUY en {buy_price} con cantidad {token_qty} ({allocation:.4f} USDT)")
            order = await self.place_order("buy", buy_price, token_qty)
            if order and "id" in order:
                order_id = order["id"]
                self.grid_orders[order_id] = {
                    "side": "buy",
                    "price": buy_price,
                    "level": -i,
                    "qty": token_qty,
                    "allocated_usdt": allocation
                }
                logging.info(f"InfinityStrategy: Orden BUY {order_id} colocada")
            else:
                logging.error(f"InfinityStrategy: Falló al colocar orden BUY en {buy_price}")
            await asyncio.sleep(0.3)

        logging.info(f"InfinityStrategy: Capital total asignado: {current_allocated:.4f} USDT")

        # Actualizar el valor correcto de capital total
        self.total_allocated_capital = current_allocated

        # Ejecutar una auditoría inicial
        await self.audit_orders()
        return True

    async def sync_order_states(self):
        try:
            exchange_orders = await self.exchange.fetch_open_orders(self.symbol)
            exchange_order_ids = {order['id'] for order in exchange_orders}

            # AGREGAR: Contador para depurar cuántas órdenes se procesan
            orders_processed = 0

            # Verificar órdenes en nuestro grid que ya no están en el exchange
            for order_id in list(self.grid_orders.keys()):
                if order_id not in exchange_order_ids:
                    try:
                        order = await self.exchange.fetch_order(order_id, self.symbol)
                        order_info = self.grid_orders[order_id]

                        if order['status'] == 'closed':
                            orders_processed += 1
                            if order_info['side'] == 'buy':
                                # Verificar si ya hay una venta colocada para esta compra
                                buy_level = order_info['level']
                                existing_sell = False

                                for _, sell_info in self.grid_orders.items():
                                    if (sell_info['side'] == 'sell' and
                                            sell_info['level'] == buy_level and
                                            sell_info.get('buy_order_id') == order_id):
                                        existing_sell = True
                                        break

                                if not existing_sell:
                                    await self.place_sell_for_executed_buy(order_id, order_info)
                            elif order_info['side'] == 'sell':
                                await self.process_executed_sell(order_id, order_info)

                        # SIEMPRE eliminar la orden del diccionario después de procesarla
                        self.grid_orders.pop(order_id, None)

                    except Exception as e:
                        logging.error(f"InfinityStrategy: Error al sincronizar estado de orden {order_id}: {e}")
                        # Si falla, eliminar la orden para evitar procesamiento repetido
                        self.grid_orders.pop(order_id, None)

            # Agregar logging adicional
            if orders_processed > 0:
                logging.info(f"InfinityStrategy: {orders_processed} órdenes procesadas en sync_order_states")

                # AGREGAR: Mostrar capital total actual
                current_allocated = sum(info["allocated_usdt"] for oid, info in self.grid_orders.items()
                                        if info["side"] == "buy")
                logging.info(f"InfinityStrategy: Capital actual tras sincronización: {current_allocated:.4f} USDT")
                logging.info(f"InfinityStrategy: Capital registrado: {self.total_allocated_capital:.4f} USDT")

                # AGREGAR: Si hay una discrepancia grande, corregir
                if abs(current_allocated - self.total_allocated_capital) > 0.05 * self.total_allocated_capital:
                    logging.warning(f"InfinityStrategy: Discrepancia detectada en capital. Actualizando.")
                    self.total_allocated_capital = current_allocated

        except Exception as e:
            logging.error(f"InfinityStrategy: Error en sync_order_states: {e}")

    async def place_sell_for_executed_buy(self, buy_order_id, buy_order_info):
        # Verificar si ya hay una orden de venta pendiente para este nivel
        for order_id, order in self.grid_orders.items():
            if (order['side'] == 'sell' and
                    order['level'] == buy_order_info['level'] and
                    order['status'] != 'closed'):
                logging.warning(f"Ya existe una orden de venta pendiente para el nivel {buy_order_info['level']}")
                return False

        # AGREGAR: Verificar que no excedemos el capital total
        current_capital = sum(info["allocated_usdt"] for oid, info in self.grid_orders.items()
                              if info["side"] == "buy")
        max_allowed_capital = self.total_balance_usdt * (1 - self.reserve_percentage / 100)

        if current_capital >= max_allowed_capital:
            logging.warning(f"InfinityStrategy: No se coloca venta - Capital máximo alcanzado: "
                            f"{current_capital:.4f}/{max_allowed_capital:.4f} USDT")
            return False

        # Calcular nuevo precio de venta
        new_price = round(buy_order_info["price"] * (1 + self.grid_interval), 8)

        # CRÍTICO: Consultar la cantidad REAL disponible
        try:
            # Obtener la moneda base (primera parte del par, ej: ADA de ADA/USDT)
            symbol_base = self.symbol.split('/')[0]
            # Obtener el balance actual
            balance = await self.exchange.fetch_balance()
            available_token = float(balance.get(symbol_base, {}).get('free', 0))

            # Obtener información del mercado para conocer la precisión exacta
            market = self.exchange.markets.get(self.symbol, {})
            amount_precision = int(market.get('precision', {}).get('amount', 8))

            # Obtener la cantidad EXACTA de la orden de compra ejecutada
            try:
                # Intentar obtener la información detallada de la orden original
                order_detail = await self.exchange.fetch_order(buy_order_id, self.symbol)
                if order_detail and order_detail.get('status') == 'closed':
                    # Usar la cantidad REAL que se ejecutó, con su precisión original
                    token_qty = order_detail['filled']
                    logging.info(f"InfinityStrategy: Usando cantidad EXACTA ejecutada de la orden: {token_qty}")
                else:
                    # Si no podemos obtener el detalle, usar la cantidad original con la precisión correcta
                    token_qty = buy_order_info["qty"]
                    logging.info(f"InfinityStrategy: Usando cantidad original de compra: {token_qty}")
            except Exception as e:
                # Si falla, usar la cantidad original
                token_qty = buy_order_info["qty"]
                logging.warning(
                    f"InfinityStrategy: Error al obtener orden {buy_order_id}, usando cantidad original: {token_qty}, error: {e}")

            # Verificar que tenemos suficiente balance
            if available_token < token_qty * 0.99:  # Verificar con un 1% de margen
                logging.warning(
                    f"InfinityStrategy: Balance insuficiente. Disponible: {available_token}, Necesario: {token_qty}")
                # Si hay alguna cantidad disponible, usar esa
                if available_token > 0:
                    # Usar el 99.5% del disponible para evitar errores
                    token_qty = available_token * 0.995
                    # Mantener la precisión EXACTA del exchange
                    token_qty = round(token_qty, amount_precision)
                    logging.info(f"InfinityStrategy: Ajustando a balance disponible: {token_qty}")
                else:
                    logging.error(f"InfinityStrategy: Sin balance disponible para vender {symbol_base}")
                    return False
        except Exception as e:
            logging.error(f"InfinityStrategy: Error al verificar balance: {e}")
            # Continuar con la cantidad original en caso de error

        logging.info(
            f"InfinityStrategy: Colocando orden SELL para BUY {buy_order_id} ejecutada a precio {new_price} con cantidad EXACTA {token_qty}")
        for attempt in range(3):
            new_order = await self.place_order("sell", new_price, token_qty)
            if new_order and "id" in new_order:
                new_order_id = new_order["id"]
                self.grid_orders[new_order_id] = {
                    "side": "sell",
                    "price": new_price,
                    "level": buy_order_info["level"],
                    "qty": token_qty,
                    "allocated_usdt": buy_order_info["allocated_usdt"],
                    "buy_order_id": buy_order_id,
                    "status": "open"
                }
                logging.info(
                    f"InfinityStrategy: Orden SELL {new_order_id} colocada para BUY {buy_order_id} con cantidad EXACTA {token_qty}")
                return True
            else:
                logging.error(
                    f"InfinityStrategy: Falló intento {attempt + 1} al colocar orden SELL para BUY {buy_order_id}")
                # Si el intento falla, verificar si el error es por cantidad insuficiente y ajustar
                if attempt < 2:
                    token_qty = token_qty * 0.995  # Reducir ligeramente la cantidad
                    token_qty = round(token_qty, amount_precision)  # Mantener precisión exacta
                    logging.info(f"InfinityStrategy: Reintentando con cantidad reducida: {token_qty}")
                await asyncio.sleep(2 ** attempt)
        return False

    async def process_executed_sell(self, sell_order_id, sell_order_info):
        # Marcar la orden de venta como cerrada
        if sell_order_id in self.grid_orders:
            self.grid_orders[sell_order_id]['status'] = 'closed'

        original_buy_price = round(sell_order_info["price"] / (1 + self.grid_interval), 4)
        token_qty = sell_order_info["qty"]
        original_allocated = sell_order_info["allocated_usdt"]

        # Calcular ganancias
        proceeds = token_qty * sell_order_info["price"]
        cost = token_qty * original_buy_price
        gross_profit = proceeds - cost
        commission_fees = self.commission * (cost + proceeds)
        net_profit = gross_profit - commission_fees

        # Procesar ganancias y obtener cantidad reinvertible
        reinvestible_profit = self.process_profit(net_profit)

        user_id = getattr(self, 'user_id', None)
        if user_id:
            # Actualizar el PNL en la estructura global
            if user_id not in users_profit_loss:
                users_profit_loss[user_id] = {}
            if self.exchange.id not in users_profit_loss[user_id]:
                users_profit_loss[user_id][self.exchange.id] = {}
            if self.symbol not in users_profit_loss[user_id][self.exchange.id]:
                users_profit_loss[user_id][self.exchange.id][self.symbol] = 0

            # Sumar la ganancia neta
            users_profit_loss[user_id][self.exchange.id][self.symbol] += net_profit

            # También guardar la transacción completa
            buy_order_info = {
                'id': sell_order_info.get('buy_order_id', 'unknown'),
                'price': original_buy_price,
                'amount': token_qty,
                'placed_time': time.time() - 3600,
                'symbol': self.symbol
            }

            sell_order_data = {
                'id': sell_order_id,
                'price': sell_order_info["price"],
                'amount': token_qty,
                'placed_time': time.time(),
                'symbol': self.symbol
            }

            save_transaction(user_id, self.exchange.id, self.symbol, buy_order_info, sell_order_data, commission_fees)

        # Verificar capital máximo antes de reinvertir
        current_capital = sum(info["allocated_usdt"] for oid, info in self.grid_orders.items()
                              if info["side"] == "buy")

        # Calcular el capital máximo considerando el capital inicial más la reinversión permitida
        base_capital = self.total_balance_usdt * (1 - self.reserve_percentage / 100)
        max_reinvestment = base_capital * (self.max_reinvestment_pct / 100)
        max_allowed_capital = base_capital + max_reinvestment

        # Si estamos cerca del límite, reducir o anular la reinversión
        if current_capital >= max_allowed_capital * 0.95:
            original_reinvestible = reinvestible_profit
            reinvestible_profit = 0
            logging.warning(f"InfinityStrategy: Reinversión cancelada por proximidad al capital máximo. "
                            f"Original: {original_reinvestible:.4f}, Ajustado: {reinvestible_profit:.4f}"
                            f"\n - Capital actual: {current_capital:.4f}"
                            f"\n - Capital máximo permitido: {max_allowed_capital:.4f} (Base: {base_capital:.4f} + Reinversión: {max_reinvestment:.4f})")

        new_allocated = original_allocated + reinvestible_profit
        new_qty = round(new_allocated / original_buy_price, 8)

        # Integrar con el sistema de PNL global
        user_id = getattr(self, 'user_id', None)
        if user_id:
            buy_order_info = {
                'id': sell_order_info.get('buy_order_id', 'unknown'),
                'price': original_buy_price,
                'amount': token_qty,
                'placed_time': time.time() - 3600,
                'symbol': self.symbol
            }

            sell_order_data = {
                'id': sell_order_id,
                'price': sell_order_info["price"],
                'amount': token_qty,
                'placed_time': time.time(),
                'symbol': self.symbol
            }

            save_transaction(user_id, self.exchange.id, self.symbol, buy_order_info, sell_order_data, commission_fees)
        logging.info(f"InfinityStrategy: Orden SELL {sell_order_id} ejecutada. Ganancia: {net_profit:.4f} USDT")
        logging.info(f"InfinityStrategy: Colocando nueva orden BUY en {original_buy_price} con reinversión")

        # Colocar nueva orden de compra con el capital actualizado
        for attempt in range(3):
            new_order = await self.place_order("buy", original_buy_price, new_qty)
            if new_order and "id" in new_order:
                new_order_id = new_order["id"]
                self.grid_orders[new_order_id] = {
                    "side": "buy",
                    "price": original_buy_price,
                    "level": sell_order_info["level"],
                    "qty": new_qty,
                    "allocated_usdt": new_allocated,
                    "status": "open"
                }
                logging.info(f"InfinityStrategy: Nueva orden BUY {new_order_id} colocada con reinversión")
                return True
            else:
                logging.error(
                    f"InfinityStrategy: Falló intento {attempt + 1} al colocar nueva orden BUY para SELL {sell_order_id}")
                await asyncio.sleep(2 ** attempt)

        return False

    async def audit_orders(self):
        try:
            logging.info(f"InfinityStrategy: Iniciando auditoría exhaustiva de órdenes para {self.symbol}")

            # 1. Obtener TODAS las órdenes del exchange (abiertas Y ejecutadas recientes)
            open_orders = await self._retry(lambda: self.exchange.fetch_open_orders(self.symbol))
            closed_orders = await self._retry(
                lambda: self.exchange.fetch_closed_orders(self.symbol, limit=100))  # Aumentar límite

            # 2. Crear índices para búsquedas eficientes
            buy_orders = {order['id']: order for order in closed_orders if
                          order['side'] == 'buy' and order['status'] == 'closed'}
            sell_orders = {order['id']: order for order in closed_orders if order['side'] == 'sell'}
            open_sell_orders = {order['id']: order for order in open_orders if order['side'] == 'sell'}

            # 3. Mapear compras a ventas existentes
            buy_with_sells = set()
            for order_id, sell_info in self.grid_orders.items():
                if sell_info['side'] == 'sell' and 'buy_order_id' in sell_info:
                    buy_with_sells.add(sell_info['buy_order_id'])

            # 4. Detectar TODAS las compras ejecutadas sin venta correspondiente
            orphan_buys = []
            for order_id, buy_order in buy_orders.items():
                # Si la compra ejecutada no tiene una venta asociada en nuestro registro
                if order_id not in buy_with_sells:
                    # Verificar también que no esté demasiado antigua (15 minutos máximo)
                    order_time = buy_order.get('timestamp', 0) / 1000
                    current_time = time.time()
                    if current_time - order_time < 15 * 60:  # 15 minutos en segundos
                        orphan_buys.append((order_id, buy_order))
                        logging.warning(
                            f"InfinityStrategy: Compra huérfana detectada: {order_id} - {buy_order['price']}")

            # 5. Procesar cada compra huérfana de forma prioritaria, sin importar cuántas sean
            for order_id, buy_order in orphan_buys:
                buy_info = {
                    "side": "buy",
                    "price": buy_order['price'],
                    "level": 0,  # Nivel genérico
                    "qty": buy_order['amount'],
                    "allocated_usdt": buy_order['price'] * buy_order['amount']
                }
                # Colocar venta inmediatamente
                success = await self.place_sell_for_executed_buy(order_id, buy_info)
                if success:
                    logging.info(f"InfinityStrategy: Venta colocada para compra huérfana {order_id}")
                else:
                    logging.error(f"InfinityStrategy: ALERTA CRÍTICA - No se pudo colocar venta para compra {order_id}")
                    # Intentar nuevamente con cantidad ajustada
                    for attempt in range(3):
                        adjusted_qty = buy_info["qty"] * (0.995 - (attempt * 0.005))
                        buy_info["qty"] = adjusted_qty
                        success = await self.place_sell_for_executed_buy(order_id, buy_info)
                        if success:
                            logging.info(
                                f"InfinityStrategy: Venta colocada para compra huérfana en reintento {attempt + 1}")
                            break

            # 6. Verificar capital total vs esperado
            current_capital = sum(info["allocated_usdt"] for info in self.grid_orders.values() if info["side"] == "buy")
            if abs(current_capital - self.total_allocated_capital) > 0.01 * self.total_allocated_capital:
                logging.warning(
                    f"InfinityStrategy: Ajustando capital total de {self.total_allocated_capital:.4f} a {current_capital:.4f}")
                self.total_allocated_capital = current_capital

            logging.info(f"InfinityStrategy: Auditoría completada. Compras huérfanas procesadas: {len(orphan_buys)}")

        except Exception as e:
            logging.error(f"InfinityStrategy: Error en audit_orders: {e}")

    async def check_orders(self):
        if not self.running:
            return

        # Verificar exposición de capital
        capital_adjusted = await self.check_capital_exposure()
        if capital_adjusted:
            # Si se ajustó el capital, no hacer más acciones en este ciclo
            return

        # Ejecutar sincronización de estado de órdenes
        await self.sync_order_states()

        # Comprobar si es momento de realizar una auditoría
        current_time = time.time()
        if current_time - self.last_audit_time >= self.audit_interval:
            await self.audit_orders()
            self.last_audit_time = current_time

        # Verificar si hay cambio significativo de precio HACIA ARRIBA
        current_ticker = await self.get_ticker()
        if current_ticker:
            current_price = current_ticker['last']

            # Solo verificar si el precio subió con respecto al precio base
            if current_price > self.last_base_price:
                price_change = (current_price - self.last_base_price) / self.last_base_price

                if price_change > self.price_threshold:
                    logging.info(f"InfinityStrategy: Aumento significativo de precio detectado: {price_change:.2%}")

                    preserved_allocations = []
                    for oid, info in sorted(self.grid_orders.items(), key=lambda x: x[1]['price'], reverse=True):
                        if info["side"] == "buy":
                            preserved_allocations.append(info["allocated_usdt"])
                    total_capital_before = sum(preserved_allocations)

                    # Reajustar la grilla hacia arriba
                    ratio = current_price / self.last_base_price
                    self.current_min_price = self.initial_min_price * ratio
                    self.base_price = current_price
                    self.last_base_price = current_price

                    logging.info(f"InfinityStrategy: Precio subió. Nuevo min_price: {self.current_min_price:.4f}")
                    logging.info(
                        f"InfinityStrategy: Reinicializando grilla con {len(preserved_allocations)} órdenes y {total_capital_before:.4f} USDT")
                    await self.initialize_grid(preserved_allocations)
                    return

            # Si el precio bajó, no hacemos nada especial
            # Simplemente continuamos verificando las órdenes existentes

        # Verificar estado de cada orden
        for order_id in list(self.grid_orders.keys()):
            order_info = self.grid_orders[order_id]
            try:
                order = await self.exchange.fetch_order(order_id, self.symbol)
            except Exception as e:
                logging.error(f"InfinityStrategy: Error al obtener orden {order_id}: {e}")
                continue

            if order and order.get("status") in ["closed", "canceled"]:
                status = order.get("status")
                if order_info["side"] == "buy":
                    if status == "closed":
                        await self.place_sell_for_executed_buy(order_id, order_info)
                    else:
                        logging.info(f"InfinityStrategy: Orden BUY {order_id} cancelada. Reintentando orden BUY.")
                        new_order = await self.place_order("buy", order_info["price"], order_info["qty"])
                        if new_order and "id" in new_order:
                            new_order_id = new_order["id"]
                            self.grid_orders[new_order_id] = {
                                "side": "buy",
                                "price": order_info["price"],
                                "level": order_info["level"],
                                "qty": order_info["qty"],
                                "allocated_usdt": order_info["allocated_usdt"]
                            }
                            logging.info(f"InfinityStrategy: Orden BUY {new_order_id} reemitida")
                        else:
                            logging.error(f"InfinityStrategy: Falló al reemitir la orden BUY {order_id}")
                    self.grid_orders.pop(order_id, None)

                elif order_info["side"] == "sell":
                    if status == "closed":
                        await self.process_executed_sell(order_id, order_info)
                    else:
                        logging.info(f"InfinityStrategy: Orden SELL {order_id} cancelada. No se reemite.")
                    self.grid_orders.pop(order_id, None)

    async def check_capital_exposure(self):
        """Verifica que no estemos excediendo el capital máximo permitido."""
        try:
            # Calcular capital actual en órdenes de compra
            buy_capital = sum(info["allocated_usdt"] for oid, info in self.grid_orders.items()
                              if info["side"] == "buy")

            # Calcular capital máximo permitido
            max_allowed = self.total_balance_usdt * (1 - self.reserve_percentage / 100)

            # Si estamos usando más del 110% del capital permitido, algo está mal
            if buy_capital > max_allowed * 1.1:
                logging.error(
                    f"InfinityStrategy: EXPOSICIÓN EXCESIVA DETECTADA: "
                    f"Usando {buy_capital:.4f} USDT cuando máximo es {max_allowed:.4f} USDT. "
                    f"Cancelando compras para reducir exposición."
                )

                # Cancelar algunas órdenes de compra empezando por las más bajas
                buy_orders = [(oid, info) for oid, info in self.grid_orders.items()
                              if info["side"] == "buy"]
                buy_orders.sort(key=lambda x: x[1]["price"])  # Ordenar por precio, ascendente

                # Cancelar órdenes hasta volver a un nivel seguro
                canceled = 0
                for oid, info in buy_orders:
                    await self.cancel_order(oid)
                    self.grid_orders.pop(oid, None)
                    buy_capital -= info["allocated_usdt"]
                    canceled += 1

                    if buy_capital <= max_allowed:
                        break

                # Actualizar capital total
                self.total_allocated_capital = buy_capital
                logging.warning(f"InfinityStrategy: Se cancelaron {canceled} órdenes para reducir exposición.")
                logging.warning(f"InfinityStrategy: Nuevo capital total: {buy_capital:.4f} USDT")

                return True
        except Exception as e:
            logging.error(f"InfinityStrategy: Error al verificar exposición de capital: {e}")

        return False

    async def cancel_all_buy_orders(self):
        logging.info("InfinityStrategy: Cancelando todas las órdenes BUY abiertas...")
        for order_id in list(self.grid_orders.keys()):
            if self.grid_orders[order_id]["side"] == "buy":
                await self.cancel_order(order_id)
                logging.info(f"InfinityStrategy: Orden BUY {order_id} cancelada")
                self.grid_orders.pop(order_id, None)
        return True

    async def start(self):
        try:
            logging.info(f"InfinityStrategy: Iniciando y verificando órdenes existentes para {self.symbol}")
            open_orders = await self.exchange.fetch_open_orders(self.symbol)
            recent_orders = await self.exchange.fetch_orders(self.symbol, limit=50)

            for order in open_orders:
                order_id = order['id']
                if order_id not in self.grid_orders:
                    side = order['side']
                    price = order['price']
                    amount = order['amount']
                    allocated = price * amount

                    self.grid_orders[order_id] = {
                        "side": side,
                        "price": price,
                        "level": 0,
                        "qty": amount,
                        "allocated_usdt": allocated
                    }
                    logging.info(f"InfinityStrategy: Registrada orden existente {side} {order_id} en {price}")

            # Verificar si hay compras ejecutadas sin ventas correspondientes
            buys_with_sells = set()
            sells = [order for order in recent_orders if order['side'] == 'sell' and order['status'] == 'closed']

            for sell in sells:
                buy_price = round(sell['price'] / (1 + self.grid_interval), 4)
                buy_candidates = [order for order in recent_orders if order['side'] == 'buy'
                                  and order['status'] == 'closed'
                                  and abs(order['price'] - buy_price) / buy_price < 0.001]

                if buy_candidates:
                    buy_candidates.sort(key=lambda x: abs(x['timestamp'] - sell['timestamp']))
                    buys_with_sells.add(buy_candidates[0]['id'])

            lonely_buys = [order for order in recent_orders
                           if order['side'] == 'buy'
                           and order['status'] == 'closed'
                           and order['id'] not in buys_with_sells]

            for buy in lonely_buys:
                buy_info = {
                    "side": "buy",
                    "price": buy['price'],
                    "level": 0,
                    "qty": buy['amount'],
                    "allocated_usdt": buy['price'] * buy['amount']
                }
                await self.place_sell_for_executed_buy(buy['id'], buy_info)
                logging.info(f"InfinityStrategy: Colocada orden SELL para compra huérfana {buy['id']}")

        except Exception as e:
            logging.error(f"InfinityStrategy: Error al iniciar y verificar órdenes existentes: {e}")

        # Calcular el capital total actualmente en uso
        buy_allocated = sum(info["allocated_usdt"] for oid, info in self.grid_orders.items() if info["side"] == "buy")
        if buy_allocated > 0:
            self.total_allocated_capital = buy_allocated
            logging.info(
                f"InfinityStrategy: Capital total en órdenes existentes: {self.total_allocated_capital:.4f} USDT")

            # Contar órdenes de compra para establecer max_grid_levels
            buy_orders_count = sum(1 for info in self.grid_orders.values() if info["side"] == "buy")
            if buy_orders_count > 0:
                self.max_grid_levels = buy_orders_count
                logging.info(
                    f"InfinityStrategy: Estableciendo número de niveles a {self.max_grid_levels} basado en órdenes existentes")

        # Continuar con la inicialización normal de la grilla
        return await self.initialize_grid()

    async def run(self):
        started = await self.start()
        if not started:
            return False

        self.last_audit_time = time.time()

        while self.running:
            await self.check_orders()
            await asyncio.sleep(self.check_interval)
        return True

    async def stop(self):
        self.running = False
        await self.cancel_all_buy_orders()

async def process_symbol(user_id, symbol_config, exchange_id):
    """
    Procesa un símbolo específico con manejo mejorado de errores y estados.
    """
    symbol = symbol_config['symbol']
    strategy = symbol_config.get('strategy', 'strategy1')

    try:
        if not validate_symbol_config(user_id, symbol_config, exchange_id):
            logging.error(f"Usuario {user_id}: Configuración inválida para {symbol} en {exchange_id}")
            users_token_running_status[user_id][exchange_id][symbol] = False
            return

        # Verificar si el token está activo en la configuración
        if not symbol_config.get('active_exchanges', {}).get(exchange_id, True):
            logging.info(f"Usuario {user_id}: Token {symbol} desactivado en configuración para {exchange_id}")
            users_token_running_status[user_id][exchange_id][symbol] = False
            return

        logging.info(f"Usuario {user_id}: Iniciando procesamiento de {symbol} en {exchange_id} con estrategia '{strategy}'")

        # Según la estrategia, llamar a la función correspondiente
        try:
            if strategy == 'strategy1':
                await process_symbol_strategy1(user_id, symbol_config, exchange_id)
            elif strategy == 'strategy2':
                await process_symbol_reinvest_strategy(user_id, symbol_config, exchange_id)
            elif strategy == 'compound':
                await process_symbol_compound(user_id, symbol_config, exchange_id)
            elif strategy == 'infinity':
                await process_symbol_infinity(user_id, symbol_config, exchange_id)
            else:
                logging.error(f"Usuario {user_id}: Estrategia '{strategy}' no reconocida para {symbol}")
                users_token_running_status[user_id][exchange_id][symbol] = False
                return
        except asyncio.CancelledError:
            logging.info(f"Usuario {user_id}: Tarea cancelada para {symbol} en {exchange_id}")
            raise
        except Exception as e:
            logging.error(f"Usuario {user_id}: Error en estrategia {strategy} para {symbol}: {str(e)}")
            # No detenemos el token aquí; se deja que el mecanismo de reintento lo maneje

    except asyncio.CancelledError:
        logging.info(f"Usuario {user_id}: Proceso de {symbol} en {exchange_id} cancelado")
        users_token_running_status[user_id][exchange_id][symbol] = False
        # Limpiar órdenes pendientes
        await cleanup_pending_orders(user_id, exchange_id, symbol)
        raise
    except Exception as e:
        logging.error(f"Usuario {user_id}: Error fatal en {symbol} para {exchange_id}: {str(e)}")
        users_token_running_status[user_id][exchange_id][symbol] = False
    finally:
        # Asegurar que el estado quede limpio
        users_token_running_status[user_id][exchange_id][symbol] = False
        if user_id in users_symbol_tasks and exchange_id in users_symbol_tasks[user_id]:
            users_symbol_tasks[user_id][exchange_id][symbol] = None

async def process_symbol_strategy1(user_id, symbol_config, exchange_id):
    symbol = symbol_config['symbol']
    strategy = symbol_config.get('strategy', 'strategy1')

    if not validate_symbol_config(user_id, symbol_config, exchange_id):
        return
    logging.info(f"Usuario {user_id}: Iniciando procesamiento de {symbol} en {exchange_id} con estrategia '{strategy}'")

    model = await initialize_model(user_id, symbol, exchange_id)
    if not model:
        return

    last_check_time, last_cleanup_time, last_audit_time = 0, 0, 0
    check_interval, cleanup_interval, audit_interval = 10, 3600, 300  # Auditoría cada 5 minutos

    # IMPORTANTE: nuevo while que comprueba exchange_running + token_running
    while (users_exchange_running_status[user_id].get(exchange_id, False) and
           users_token_running_status[user_id][exchange_id].get(symbol, False)):

        try:
            # Verificar si el símbolo está activo en configuración
            if not symbol_config.get('active_exchanges', {}).get(exchange_id, True):
                await asyncio.sleep(5)
                continue

            current_time = time.time()
            await perform_periodic_tasks(user_id, current_time, last_check_time, last_cleanup_time,
                                         check_interval, cleanup_interval, exchange_id, symbol, symbol_config)
            last_check_time, last_cleanup_time = update_check_times(
                current_time, last_check_time, last_cleanup_time, check_interval, cleanup_interval
            )

            # Auditoría periódica de órdenes
            if current_time - last_audit_time >= audit_interval:
                await audit_orders(user_id, exchange_id, symbol, symbol_config)
                last_audit_time = current_time

            await update_pending_sells(user_id, exchange_id, symbol)
            await check_filled_sell_orders(user_id, exchange_id, symbol)

            # Obtener el precio de mercado antes de llamar a manage_symbol_reactivation
            market_prices_data = await get_market_prices_async(user_id, exchange_id)
            market_price = market_prices_data.get(symbol)
            logging.info(f"Usuario {user_id}: Precio de mercado para {symbol} en {exchange_id}: {market_price}")

            if market_price is None:
                await asyncio.sleep(10)
                continue

            # Pérdida diaria
            await calculate_daily_loss(user_id, symbol, exchange_id)
            daily_loss = users_daily_losses[user_id][exchange_id][symbol]
            logging.info(f"Usuario {user_id}: Pérdida diaria actual para {symbol} en {exchange_id}: {daily_loss}%")

            await manage_symbol_reactivation(user_id, symbol, exchange_id, market_price, symbol_config)

            if not should_continue_processing(user_id, exchange_id, symbol):
                logging.info(f"Usuario {user_id}: El símbolo {symbol} está inactivo en {exchange_id}")
                await asyncio.sleep(10)
                continue

            # Detectar caídas repentinas y suspender trading si es necesario
            sudden_drop = await detect_sudden_drop(user_id, symbol, exchange_id,
                                                   threshold_percentage=2, time_period_minutes=15)
            if sudden_drop:
                users_active_symbols[user_id][exchange_id][symbol] = False
                logging.info(
                    f"Usuario {user_id}: Trading detenido para {symbol} en {exchange_id} debido a caída repentina de precio"
                )
                users_reactivation_thresholds[user_id][exchange_id][symbol] = market_price * 1.01
                await asyncio.sleep(60)
                continue

            ohlcv_data = await fetch_latest_ohlcv(user_id, symbol, exchange_id)
            if ohlcv_data.empty:
                await asyncio.sleep(10)
                continue

            predicted_price = predict_next_price(user_id, model, symbol, exchange_id, ohlcv_data)
            logging.info(f"Usuario {user_id}: Precio predicho para {symbol} en {exchange_id}: {predicted_price}")

            await process_trading_decision(user_id, predicted_price, market_price, symbol_config, exchange_id, symbol)
            await manage_daily_loss(user_id, symbol, exchange_id, market_price, symbol_config)

            await asyncio.sleep(1)

        except Exception as e:
            logging.error(f"Usuario {user_id}: Error en process_symbol_strategy1({symbol},{exchange_id}): {e}",
                          exc_info=True)
            await asyncio.sleep(10)

    logging.info(f"Usuario {user_id}: Finalizando process_symbol_strategy1 para {symbol} en {exchange_id}")


async def process_symbol_compound(user_id, symbol_config, exchange_id):
    """
    Estrategia COMPOUND con Spread Escalonado y gestión ordenada de la grilla
    """
    symbol = symbol_config['symbol']

    if not validate_symbol_config(user_id, symbol_config, exchange_id):
        return

    logging.info(f"Usuario {user_id}: Iniciando COMPOUND para {symbol} en {exchange_id}...")

    # Reinicializar estructuras específicas para compound para evitar interferencias
    reinitialize_compound_structures(user_id, exchange_id, symbol)

    model = await initialize_model(user_id, symbol, exchange_id)
    if not model:
        logging.error(f"Usuario {user_id}: No se pudo inicializar modelo para {symbol} en {exchange_id}. Abortando.")
        return

    last_check_time, last_cleanup_time, last_audit_time = 0, 0, 0
    check_interval = 10
    cleanup_interval = 3600
    audit_interval = 30

    # Obtener parámetros con validación
    if not isinstance(symbol_config.get('initial_capital'), (int, float)) or symbol_config.get('initial_capital',
                                                                                               0) <= 0:
        base_capital = 5000.0
        symbol_config['initial_capital'] = base_capital
        logging.warning(f"Usuario {user_id}: initial_capital inválido para {symbol}, ajustando a {base_capital}")
    else:
        base_capital = float(symbol_config.get('initial_capital', 5000.0))

    if not isinstance(symbol_config.get('max_sell_orders'), int) or symbol_config.get('max_sell_orders', 0) <= 0:
        max_sell_orders = 15
        symbol_config['max_sell_orders'] = max_sell_orders
        logging.warning(f"Usuario {user_id}: max_sell_orders inválido para {symbol}, ajustando a {max_sell_orders}")
        save_encrypted_config(user_id)
    else:
        max_sell_orders = int(symbol_config.get('max_sell_orders', 15))

    logging.info(
        f"Usuario {user_id}: Parámetros COMPOUND validados: base_capital={base_capital}, max_sell_orders={max_sell_orders}")

    # Inicializar reinversión con validación
    if user_id not in users_reinvested_profits:
        users_reinvested_profits[user_id] = {}
    if exchange_id not in users_reinvested_profits[user_id]:
        users_reinvested_profits[user_id][exchange_id] = {}
    if symbol not in users_reinvested_profits[user_id][exchange_id]:
        users_reinvested_profits[user_id][exchange_id][symbol] = 0.0

    # Verificar estructuras críticas
    if user_id not in users_open_orders or exchange_id not in users_open_orders[user_id] or symbol not in \
            users_open_orders[user_id][exchange_id]:
        initialize_symbol(user_id, exchange_id, symbol)
        logging.info(f"Usuario {user_id}: Estructuras de órdenes inicializadas para {symbol}")

    while (users_exchange_running_status[user_id].get(exchange_id, False) and
           users_token_running_status[user_id][exchange_id].get(symbol, False)):

        try:
            current_time = time.time()

            # Tareas periódicas
            if current_time - last_check_time >= check_interval:
                await manage_open_buy_orders(user_id, exchange_id, symbol,
                                             symbol_config['order_expiration'],
                                             symbol_config['take_profit'])
                await update_pending_sells(user_id, exchange_id, symbol)
                await check_filled_sell_orders(user_id, exchange_id, symbol)
                last_check_time = current_time

            if current_time - last_cleanup_time >= cleanup_interval:
                await clean_old_orders(user_id, exchange_id, symbol)
                last_cleanup_time = current_time

            if current_time - last_audit_time >= audit_interval:
                await audit_orders(user_id, exchange_id, symbol, symbol_config)
                last_audit_time = current_time

            # Obtener precio actual
            market_data = await get_market_prices_async(user_id, exchange_id)
            market_price = market_data.get(symbol)

            if market_price is None:
                logging.warning(f"Usuario {user_id}: Sin market_price para {symbol} en {exchange_id}.")
                await asyncio.sleep(10)
                continue

            # Verificaciones de estado
            await calculate_daily_loss(user_id, symbol, exchange_id)
            daily_loss = users_daily_losses[user_id][exchange_id][symbol]
            logging.info(f"Usuario {user_id}: Pérdida diaria {symbol} en {exchange_id}: {daily_loss:.2f}%")

            await manage_symbol_reactivation(user_id, symbol, exchange_id, market_price, symbol_config)
            if not should_continue_processing(user_id, exchange_id, symbol):
                await asyncio.sleep(10)
                continue

            sudden_drop = await detect_sudden_drop(user_id, symbol, exchange_id,
                                                   threshold_percentage=2,
                                                   time_period_minutes=15)
            if sudden_drop:
                users_active_symbols[user_id][exchange_id][symbol] = False
                users_reactivation_thresholds[user_id][exchange_id][symbol] = market_price * 1.01
                await asyncio.sleep(60)
                continue

            # Análisis y predicción
            ohlcv = await fetch_latest_ohlcv(user_id, symbol, exchange_id)
            if ohlcv.empty:
                await asyncio.sleep(10)
                continue

            predicted_price = predict_next_price(user_id, model, symbol, exchange_id, ohlcv)
            logging.info(
                f"Usuario {user_id}: [compound] Predicción {symbol}={predicted_price:.4f}, mercado={market_price:.4f}")

            if predicted_price > market_price:
                # Verificar órdenes existentes
                exchange = users_exchanges[user_id][exchange_id]
                open_orders = await exchange.fetch_open_orders(symbol)

                # Contar órdenes de venta con seguridad
                current_sell_orders = 0
                for o in open_orders:
                    if isinstance(o, dict) and o.get('side') == 'sell':
                        current_sell_orders += 1

                # Asegurar que max_sell_orders sea un valor positivo
                max_sell_orders = int(symbol_config.get('max_sell_orders', 15))
                if max_sell_orders <= 0:
                    max_sell_orders = 15
                    logging.warning(f"Usuario {user_id}: [compound] max_sell_orders inválido, ajustando a 15")

                remaining_sell_slots = max(0, max_sell_orders - current_sell_orders)

                logging.info(
                    f"Usuario {user_id}: [compound] Estado actual:"
                    f"\n - Ventas abiertas: {current_sell_orders}/{max_sell_orders}"
                    f"\n - Slots disponibles: {remaining_sell_slots}"
                    f"\n - Órdenes abiertas totales: {len(open_orders)}"
                )

                if remaining_sell_slots > 0:
                    # Obtener siguiente nivel disponible
                    grid_slots = await get_ordered_grid_slots(user_id, exchange_id, symbol, market_price, symbol_config)

                    # Verificar si grid_slots está vacío y mostrar mensaje detallado
                    if not grid_slots:
                        logging.warning(
                            f"Usuario {user_id}: [compound] No se encontraron niveles disponibles para {symbol}.")
                        logging.info(
                            f"Usuario {user_id}: [compound] Verificando spread configurado: {symbol_config.get('spread', 'No definido')}")
                        # Intentar con un spread mínimo garantizado
                        if 'spread' in symbol_config and symbol_config['spread'] > 0:
                            logging.info(f"Usuario {user_id}: [compound] Intentando con un nivel mínimo forzado")
                            price_level = market_price * (1 - symbol_config['spread'])
                            grid_slots = [price_level]

                    if grid_slots:
                        price_level = grid_slots[0]
                        order_capital = await get_compound_portion(
                            user_id, exchange_id, symbol, base_capital, max_sell_orders
                        )
                        buy_amount = order_capital / price_level

                        new_buy_order = await place_order_async(
                            user_id, symbol, 'buy', buy_amount, price_level, exchange_id
                        )

                        if new_buy_order:
                            logging.info(
                                f"Usuario {user_id}: [compound] Orden colocada en nivel {price_level:.8f}")
                            asyncio.create_task(
                                process_placed_order(
                                    user_id, new_buy_order, exchange_id, symbol,
                                    'buy', buy_amount, price_level, symbol_config
                                )
                            )

                        await asyncio.sleep(1)  # Breve pausa entre órdenes
                    else:
                        logging.info(f"Usuario {user_id}: [compound] No hay niveles disponibles que cumplan el spread")
                else:
                    logging.info(
                        f"Usuario {user_id}: [compound] Máximo de ventas alcanzado ({current_sell_orders}/{max_sell_orders})")

            await manage_daily_loss(user_id, symbol, exchange_id, market_price, symbol_config)
            await asyncio.sleep(10)

        except Exception as e:
            logging.error(f"Usuario {user_id}: [compound] Error en {symbol} {exchange_id}: {e}", exc_info=True)
            await asyncio.sleep(10)

    logging.info(f"Usuario {user_id}: Se cierra process_symbol_compound para {symbol} en {exchange_id}.")


async def process_symbol_infinity(user_id, symbol_config, exchange_id):
    exchange = users_exchanges[user_id][exchange_id]
    try:
        total_balance_usdt = float(symbol_config.get('total_balance_usdt', 1000))
        grid_interval = float(symbol_config.get('grid_interval', 0.002))
        min_price = float(symbol_config.get('min_price', 8000.00))
        check_interval = float(symbol_config.get('check_interval', 5))
        commission = float(symbol_config.get('commission', 0.001))
        reinvestment_percentage = float(symbol_config.get('reinvestment_percentage', 75.0))
        max_reinvestment_pct = float(symbol_config.get('max_reinvestment_pct', 50.0))
        reserve_percentage = float(symbol_config.get('reserve_percentage', 20.0))
    except Exception as e:
        logging.error(f"Error parsing infinity strategy parameters: {e}")
        return

    infinity_bot = InfinityStrategy(
        exchange,
        symbol_config['symbol'],
        total_balance_usdt,
        grid_interval,
        min_price,
        check_interval,
        commission,
        reinvestment_percentage,
        max_reinvestment_pct,
        reserve_percentage,
        user_id=user_id  # Pasamos el user_id aquí
    )
    users_token_running_status[user_id][exchange_id][symbol_config['symbol']] = True
    try:
        await infinity_bot.run()
    except asyncio.CancelledError:
        logging.info(f"Infinity strategy for {symbol_config['symbol']} cancelled")
    finally:
        # Al detener el token, se llama al método stop() para frenar el loop y cancelar órdenes
        await infinity_bot.stop()
        users_token_running_status[user_id][exchange_id][symbol_config['symbol']] = False

def validate_symbol_config(user_id, symbol_config, exchange_id):
    # Quitar trade_amount de always_required:
    always_required = ['strategy']

    strategy = symbol_config.get('strategy')

    # Luego, según la estrategia, armar la lista de campos que se necesitan:
    if strategy in ['strategy1', 'strategy2', 'strategy4']:
        required_fields = ['spread', 'take_profit', 'max_orders', 'max_sell_orders', 'order_expiration', 'trade_amount']
    elif strategy == 'compound':
        required_fields = ['initial_capital', 'spread', 'take_profit', 'max_orders', 'order_expiration']
    elif strategy == 'infinity':
        required_fields = [
            'total_balance_usdt', 'grid_interval', 'min_price', 'check_interval',
            'commission', 'reinvestment_percentage', 'max_reinvestment_pct', 'reserve_percentage'
        ]
    else:
        required_fields = []

    missing_always = [field for field in always_required if
                      field not in symbol_config or symbol_config[field] in (None, '')]
    if missing_always:
        logging.error(
            f"Usuario {user_id}: Faltan campos obligatorios: {missing_always} para {symbol_config['symbol']} en {exchange_id}")
        return False

    missing_fields = [field for field in required_fields if
                      field not in symbol_config or symbol_config[field] in (None, '')]
    if missing_fields:
        logging.error(
            f"Usuario {user_id}: Faltan campos según la estrategia '{strategy}': {missing_fields} para {symbol_config['symbol']} en {exchange_id}")
        return False

    return True


async def initialize_model(user_id, symbol, exchange_id):
    try:
        data = await fetch_ohlcv_async(user_id, symbol, exchange_id, timeframe='1h', limit=500)
        return train_model(user_id, data, symbol, exchange_id)
    except Exception as e:
        logging.error(f"Usuario {user_id}: Error al entrenar el modelo para {symbol} en {exchange_id}: {e}",
                      exc_info=True)
        return None


async def perform_periodic_tasks(user_id, current_time, last_check_time, last_cleanup_time, check_interval,
                                 cleanup_interval, exchange_id, symbol, symbol_config):
    if current_time - last_check_time >= check_interval:
        await manage_open_buy_orders(user_id, exchange_id, symbol, symbol_config['order_expiration'],
                                     symbol_config['take_profit'])
        await update_pending_sells(user_id, exchange_id, symbol)
        await check_filled_sell_orders(user_id, exchange_id, symbol)
    if current_time - last_cleanup_time >= cleanup_interval:
        await clean_old_orders(user_id, exchange_id, symbol)


def update_check_times(current_time, last_check_time, last_cleanup_time, check_interval, cleanup_interval):
    new_last_check_time = current_time if current_time - last_check_time >= check_interval else last_check_time
    new_last_cleanup_time = current_time if current_time - last_cleanup_time >= cleanup_interval else last_cleanup_time
    return new_last_check_time, new_last_cleanup_time


def should_continue_processing(user_id, exchange_id, symbol):
    if symbol not in users_active_symbols[user_id][exchange_id]:
        initialize_symbol(user_id, exchange_id, symbol)
        logging.warning(
            f"Usuario {user_id}: Símbolo {symbol} no estaba en active_symbols para {exchange_id}. Se ha inicializado automáticamente.")
    return users_active_symbols[user_id][exchange_id][symbol]


async def get_current_market_price(user_id, exchange_id, symbol):
    prices = await get_market_prices_async(user_id, exchange_id)
    market_price = prices.get(symbol)
    if market_price is None:
        logging.warning(f"Usuario {user_id}: No se pudo obtener el precio de mercado para {symbol} en {exchange_id}.")
    return market_price


async def get_open_sell_orders(user_id, exchange_id, symbol):
    try:
        exchange = users_exchanges[user_id][exchange_id]
        open_sell_orders = await exchange.fetch_open_orders(symbol)
        open_sell_orders = [order for order in open_sell_orders if order['side'] == 'sell']
        return open_sell_orders
    except Exception as e:
        logging.error(
            f"Usuario {user_id}: Error al obtener órdenes de venta abiertas para {symbol} en {exchange_id}: {e}")
        return []


async def fetch_latest_ohlcv(user_id, symbol, exchange_id):
    ohlcv = await fetch_ohlcv_async(user_id, symbol, exchange_id, timeframe='1h', limit=1)
    if ohlcv.empty:
        logging.warning(f"Usuario {user_id}: No se obtuvieron datos OHLCV para {symbol} en {exchange_id}.")
    return ohlcv


async def process_trading_decision(user_id, predicted_price, market_price, symbol_config, exchange_id, symbol):
    # 1) Calcula el monto reinvertido ANTES de decidir comprar (en lugar de usar symbol_config['trade_amount']).
    current_trade_amount = get_reinvested_amount(
        user_id,
        exchange_id,
        symbol,
        symbol_config['trade_amount']  # Este es el monto base configurado
    )

    if predicted_price > market_price:
        target_buy_price = calculate_target_buy_price(market_price, symbol_config['spread'])
        if target_buy_price > 0 and can_place_order(user_id, exchange_id, symbol, 'buy', symbol_config):
            # 2) Llamada a place_buy_order usando current_trade_amount (ya con ganancias reinvertidas).
            await place_buy_order(
                user_id,
                symbol,
                current_trade_amount,
                target_buy_price,
                exchange_id,
                symbol_config['order_expiration'],
                symbol_config
            )
        else:
            logging.info(
                f"Usuario {user_id}: No se colocará orden de compra. predicted_price={predicted_price}, market_price={market_price}"
            )
    else:
        logging.info(
            f"Usuario {user_id}: Predicted price {predicted_price} is not greater than market price {market_price}. No action taken."
        )


def calculate_target_buy_price(market_price, spread):
    target_buy_price = market_price * (1 - spread)
    if target_buy_price <= 0:
        logging.error(f"Target Buy Price calculado es inválido: {target_buy_price}. Verifica el valor del spread.")
        return None
    return target_buy_price


async def place_buy_order(user_id, symbol, trade_amount, target_buy_price, exchange_id, order_timeout, symbol_config):
    order = await place_order_async(user_id, symbol, 'buy', trade_amount, target_buy_price, exchange_id)
    if order:
        logging.debug(
            f"Usuario {user_id}: Orden de compra colocada: {order['id']} para {symbol} en {exchange_id} a {target_buy_price}")
        await process_placed_order(user_id, order, exchange_id, symbol, 'buy', trade_amount, target_buy_price,
                                   symbol_config)
    else:
        logging.error(f"Usuario {user_id}: No se pudo colocar la orden de compra para {symbol} en {exchange_id}")


async def manage_daily_loss(user_id, symbol, exchange_id, market_price, symbol_config):
    await calculate_daily_loss(user_id, symbol, exchange_id)
    daily_loss = users_daily_losses[user_id][exchange_id][symbol]

    if symbol_config['daily_loss_max'] is None:
        return  # No hacer nada si la pérdida diaria está deshabilitada

    # Convertir daily_loss_max a un número positivo para comparación
    daily_loss_max = abs(symbol_config['daily_loss_max'])

    # Detener el trading solo si hay una pérdida (número negativo) que excede el límite
    if daily_loss < 0 and abs(daily_loss) >= daily_loss_max:
        users_active_symbols[user_id][exchange_id][symbol] = False
        # Calcular el precio de reactivación
        reactivation_percentage = symbol_config.get('reactivation_threshold', 5) / 100
        users_reactivation_thresholds[user_id][exchange_id][symbol] = market_price * (1 + reactivation_percentage)
        logging.info(
            f"Usuario {user_id}: Pérdida diaria máxima alcanzada para {symbol} en {exchange_id}, deteniendo operaciones. Pérdida actual: {daily_loss}%")
    else:
        logging.info(f"Usuario {user_id}: Cambio diario actual para {symbol} en {exchange_id}: {daily_loss}%")


async def calculate_daily_loss(user_id, symbol, exchange_id):
    try:
        ohlcv_data = await fetch_ohlcv_async(user_id, symbol, exchange_id, timeframe='1d', limit=2)
        if ohlcv_data.empty:
            logging.warning(
                f"Usuario {user_id}: No se pudieron obtener datos OHLCV diarios para {symbol} en {exchange_id}")
            return
        today = datetime.utcnow().date()
        ohlcv_data['date'] = ohlcv_data['timestamp'].dt.date
        today_data = ohlcv_data[ohlcv_data['date'] == today]
        if today_data.empty:
            logging.warning(f"Usuario {user_id}: No hay datos OHLCV para hoy para {symbol} en {exchange_id}")
            return
        opening_price = today_data.iloc[0]['open']
        current_price = users_market_prices[user_id][exchange_id][symbol]
        if opening_price == 0:
            logging.warning(f"Usuario {user_id}: El precio de apertura es 0 para {symbol} en {exchange_id}")
            return
        daily_change_percentage = ((current_price - opening_price) / opening_price) * 100
        users_daily_losses[user_id][exchange_id][symbol] = daily_change_percentage
        logging.info(
            f"Usuario {user_id}: Pérdida diaria calculada para {symbol} en {exchange_id}: {daily_change_percentage}%")
    except Exception as e:
        logging.error(f"Usuario {user_id}: Error al calcular la pérdida diaria para {symbol} en {exchange_id}: {e}")


async def detect_sudden_drop(user_id, symbol, exchange_id, threshold_percentage=5, time_period_minutes=15):
    try:
        limit = time_period_minutes
        ohlcv_data = await fetch_ohlcv_async(user_id, symbol, exchange_id, timeframe='1m', limit=limit)
        if ohlcv_data.empty:
            logging.warning(
                f"Usuario {user_id}: No se pudieron obtener datos OHLCV para detectar caídas repentinas para {symbol} en {exchange_id}")
            return False
        start_price = ohlcv_data.iloc[0]['open']
        end_price = ohlcv_data.iloc[-1]['close']
        price_change_percentage = ((end_price - start_price) / start_price) * 100
        if price_change_percentage <= -threshold_percentage:
            logging.info(
                f"Usuario {user_id}: Se detectó una caída repentina de {price_change_percentage}% para {symbol} en {exchange_id}")
            return True
        else:
            return False
    except Exception as e:
        logging.error(f"Usuario {user_id}: Error al detectar caídas repentinas para {symbol} en {exchange_id}: {e}")
        return False


async def manage_symbol_reactivation(user_id, symbol, exchange_id, market_price, symbol_config):
    daily_loss = users_daily_losses[user_id][exchange_id][symbol]
    if not users_active_symbols[user_id][exchange_id][symbol]:
        if symbol_config.get('reactivation_threshold') is not None:
            if abs(daily_loss) <= symbol_config['reactivation_threshold']:
                users_active_symbols[user_id][exchange_id][symbol] = True
                logging.info(
                    f"Usuario {user_id}: Símbolo {symbol} en {exchange_id} reactivado para trading. Pérdida diaria actual: {daily_loss}%")
        else:
            if abs(daily_loss) < symbol_config['daily_loss_max']:
                users_active_symbols[user_id][exchange_id][symbol] = True
                logging.info(
                    f"Usuario {user_id}: Símbolo {symbol} en {exchange_id} reactivado para trading. Pérdida diaria actual: {daily_loss}%")


async def manage_open_buy_orders(user_id, exchange_id, symbol, order_timeout, take_profit):
    current_time = time.time()
    order_timeout_seconds = order_timeout * 60
    orders_to_remove = []
    for order_entry in list(users_open_orders[user_id][exchange_id][symbol]):
        order_id = order_entry.get('id', 'ID desconocido')
        placed_time = order_entry.get('placed_time')
        side = order_entry.get('side')
        if not placed_time or not side:
            logging.warning(
                f"Usuario {user_id}: Orden {order_id} no tiene 'placed_time' o 'side'. Verificando estado en el exchange.")
            try:
                order = await users_exchanges[user_id][exchange_id].fetch_order(order_id, symbol)
                if order['status'] == 'open':
                    placed_time = order.get('timestamp', current_time) / 1000  # Convertir ms a segundos
                    order_entry['placed_time'] = placed_time
                    order_entry['side'] = order['side']
                else:
                    logging.info(f"Usuario {user_id}: Orden {order_id} ya no está abierta. Removiéndola.")
                    orders_to_remove.append(order_entry)
                    continue
            except Exception as e:
                logging.error(f"Usuario {user_id}: Error al verificar el estado de la orden {order_id}: {e}")
                continue
        if side != 'buy':
            continue  # Ignorar órdenes que no sean de compra
        order_age = current_time - placed_time
        if order_age > order_timeout_seconds:
            try:
                await cancel_order_async(user_id, order_id, symbol, exchange_id)
                logging.info(
                    f"Usuario {user_id}: Orden {order_id} cancelada automáticamente tras exceder {order_timeout} minutos.")
                orders_to_remove.append(order_entry)
            except Exception as e:
                logging.error(f"Usuario {user_id}: Error al intentar cancelar la orden {order_id} para {symbol}: {e}")
    for order_to_remove in orders_to_remove:
        if order_to_remove in users_open_orders[user_id][exchange_id][symbol]:
            users_open_orders[user_id][exchange_id][symbol].remove(order_to_remove)
        else:
            logging.warning(
                f"Usuario {user_id}: Orden {order_to_remove.get('id', 'ID desconocido')} ya no está en la lista de órdenes abiertas.")


async def cleanup_pending_orders(user_id, exchange_id, symbol):
    """
    Limpia todas las órdenes pendientes de un símbolo.
    """
    try:
        # Cancelar órdenes de compra abiertas
        if exchange_id in users_open_orders[user_id] and symbol in users_open_orders[user_id][exchange_id]:
            for order in list(users_open_orders[user_id][exchange_id][symbol]):
                if order['side'] == 'buy':
                    try:
                        await cancel_order_async(user_id, order['id'], symbol, exchange_id)
                    except Exception as e:
                        logging.error(f"Error cancelando orden {order['id']}: {str(e)}")

        # Limpiar estructuras de datos
        users_open_orders[user_id][exchange_id][symbol] = []
        users_pending_sells[user_id][exchange_id][symbol] = []

        # Limpiar OrderTracker
        if exchange_id in users_order_trackers[user_id].buy_orders:
            users_order_trackers[user_id].buy_orders[exchange_id][symbol] = {}
        if exchange_id in users_order_trackers[user_id].sell_orders:
            users_order_trackers[user_id].sell_orders[exchange_id][symbol] = {}

        logging.info(f"Usuario {user_id}: Limpieza de órdenes completada para {symbol} en {exchange_id}")
    except Exception as e:
        logging.error(f"Usuario {user_id}: Error en cleanup_pending_orders para {symbol}: {str(e)}")

async def clean_old_orders(user_id, exchange_id, symbol, max_age=24 * 60 * 60):
    current_time = time.time()
    users_open_orders[user_id][exchange_id][symbol] = [
        order for order in users_open_orders[user_id][exchange_id][symbol] if
        current_time - order['placed_time'] < max_age
    ]
    users_pending_sells[user_id][exchange_id][symbol] = [
        order for order in users_pending_sells[user_id][exchange_id][symbol] if
        current_time - order['placed_time'] < max_age
    ]
    logging.info(f"Usuario {user_id}: Órdenes antiguas limpiadas para {symbol} en {exchange_id}")


def find_matching_buy_order(user_id, exchange_id, symbol, buy_order_id):
    return users_order_trackers[user_id].buy_orders[exchange_id][symbol].get(buy_order_id)


def remove_buy_order(user_id, exchange_id, symbol, order_id):
    users_open_orders[user_id][exchange_id][symbol] = [order for order in
                                                       users_open_orders[user_id][exchange_id][symbol] if
                                                       order['id'] != order_id]


async def get_commission(user_id, exchange_id, symbol, amount, price):
    try:
        exchange = users_exchanges[user_id][exchange_id]
        fee = await exchange.fetch_trading_fee(symbol)
        return fee['taker'] * amount * price
    except:
        return users_commission_rate[user_id] * amount * price

async def toggle_token(user_id, exchange_id, symbol):
    if exchange_id not in users_exchanges_config[user_id]:
        logging.error(f"Usuario {user_id}: El exchange {exchange_id} no existe.")
        return "El exchange especificado no existe."

    symbol_entry = next((s for s in users_symbols_config[user_id] if s['symbol'] == symbol), None)
    if not symbol_entry:
        logging.error(f"Usuario {user_id}: El token '{symbol}' no existe.")
        return f"El token '{symbol}' no existe."

    if exchange_id not in symbol_entry['exchanges']:
        logging.error(f"Usuario {user_id}: El token '{symbol}' no está asociado con el exchange '{exchange_id}'.")
        return f"El token '{symbol}' no está asociado con el exchange '{exchange_id}'."

    if 'active_exchanges' not in symbol_entry:
        symbol_entry['active_exchanges'] = {}
    if exchange_id not in symbol_entry['active_exchanges']:
        symbol_entry['active_exchanges'][exchange_id] = True

    current_status = symbol_entry['active_exchanges'][exchange_id]
    new_status = not current_status
    symbol_entry['active_exchanges'][exchange_id] = new_status

    # Si estamos desactivando el token
    if not new_status:
        # Si la estrategia es 'infinity', forzar la salida del bucle en la instancia de InfinityStrategy
        if symbol_entry.get('strategy') == 'infinity':
            if (user_id in infinity_strategy_instances and
                exchange_id in infinity_strategy_instances[user_id] and
                symbol in infinity_strategy_instances[user_id][exchange_id]):
                infinity_strategy_instances[user_id][exchange_id][symbol].running = False
                logging.info(f"Usuario {user_id}: InfinityStrategy para {symbol} se ha marcado para detenerse.")

        # Detener la tarea del token si existe
        if (user_id in users_token_running_status and
                exchange_id in users_token_running_status[user_id] and
                symbol in users_token_running_status[user_id][exchange_id]):
            users_token_running_status[user_id][exchange_id][symbol] = False

            # Intentar detener la tarea existente
            if (user_id in users_symbol_tasks and
                    exchange_id in users_symbol_tasks[user_id] and
                    symbol in users_symbol_tasks[user_id][exchange_id]):

                task = users_symbol_tasks[user_id][exchange_id][symbol]
                if task and not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                    users_symbol_tasks[user_id][exchange_id][symbol] = None

                # Cancelar órdenes abiertas del token
                if exchange_id in users_open_orders[user_id] and symbol in users_open_orders[user_id][exchange_id]:
                    orders_to_cancel = users_open_orders[user_id][exchange_id][symbol]
                    for order in orders_to_cancel:
                        if order['side'] == 'buy':
                            try:
                                await cancel_order_async(user_id, order['id'], symbol, exchange_id)
                            except Exception as e:
                                logging.error(f"Error al cancelar orden {order['id']}: {str(e)}")
                    # Limpiar lista de órdenes
                    users_open_orders[user_id][exchange_id][symbol] = []

                logging.info(f"Usuario {user_id}: Tarea del token {symbol} detenida y órdenes canceladas.")

    # Si estamos activando el token
    elif new_status and users_exchange_running_status[user_id].get(exchange_id, False):
        # Reiniciar el token solo si el exchange está corriendo
        await start_symbol_task(user_id, exchange_id, symbol)

    status_msg = "habilitado" if new_status else "deshabilitado"
    save_encrypted_config(user_id)
    return f"Token '{symbol}' en exchange '{exchange_id}' ha sido {status_msg}."


def train_model(user_id, data, symbol, exchange_id):
    model_filename = f'price_prediction_model_{user_id}_{exchange_id}_{symbol.replace("/", "_")}.pkl'
    retrain_interval = 12 * 60 * 60  # 12 horas

    if os.path.exists(model_filename) and (time.time() - os.path.getmtime(model_filename)) < retrain_interval:
        logging.info(f"Usuario {user_id}: Cargando modelo existente para {symbol} en {exchange_id}")
        return joblib.load(model_filename)

    data = data.tail(1000).copy()
    data['target'] = data['close'].shift(-1)
    data.dropna(inplace=True)
    X = data[['open', 'high', 'low', 'close', 'volume']]
    y = data['target']

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    param_distributions = {
        'n_estimators': randint(100, 500),
        'max_depth': randint(10, 110),
        'min_samples_split': randint(2, 21),
        'min_samples_leaf': randint(1, 11),
        'bootstrap': [True, False]
    }

    rf = RandomForestRegressor(random_state=42)

    random_search = RandomizedSearchCV(
        estimator=rf,
        param_distributions=param_distributions,
        n_iter=50,
        cv=5,
        verbose=0,
        random_state=42,
        n_jobs=-1
    )

    random_search.fit(X_train, y_train)
    best_model = random_search.best_estimator_
    joblib.dump(best_model, model_filename)
    logging.info(f"Usuario {user_id}: Modelo entrenado y guardado para {symbol} en {exchange_id}")
    return best_model


def predict_next_price(user_id, model, symbol, exchange_id, data):
    row = data.iloc[-1]
    feature_names = ['open', 'high', 'low', 'close', 'volume']
    row_df = pd.DataFrame([row[feature_names]], columns=feature_names)
    prediction = model.predict(row_df)[0]
    logging.info(f"Usuario {user_id}: Predicción del próximo precio para {symbol} en {exchange_id}: {prediction}")
    if exchange_id not in users_predicted_prices[user_id]:
        users_predicted_prices[user_id][exchange_id] = {}
    users_predicted_prices[user_id][exchange_id][symbol] = prediction
    return prediction

async def get_market_prices_async(user_id, exchange_id, retries=5):
    symbols = users_exchanges_config[user_id][exchange_id]['symbols']
    for attempt in range(retries):
        try:
            # Usar rate limiter específico
            rate_limiter = get_rate_limiter(user_id, exchange_id)
            async with rate_limiter:
                tickers = await users_exchanges[user_id][exchange_id].fetch_tickers(symbols)
            for symbol, ticker in tickers.items():
                if exchange_id not in users_market_prices[user_id]:
                    users_market_prices[user_id][exchange_id] = {}
                users_market_prices[user_id][exchange_id][symbol] = ticker['last']
            return {symbol: users_market_prices[user_id][exchange_id][symbol] for symbol in symbols}
        except Exception as e:
            logging.error(f"Usuario {user_id}: Error al obtener precios de mercado para {exchange_id}: {e}")
            if attempt == retries - 1:
                raise
            await asyncio.sleep(2 ** attempt)


async def fetch_ohlcv_async(user_id, symbol, exchange_id, timeframe='1h', limit=500, retries=5):
    for attempt in range(retries):
        try:
            data = await users_exchanges[user_id][exchange_id].fetch_ohlcv(symbol, timeframe, limit=limit)
            df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except Exception as e:
            logging.error(f"Usuario {user_id}: Error al obtener datos OHLCV para {symbol} en {exchange_id}: {e}")
            if attempt == retries - 1:
                raise
            await asyncio.sleep(2 ** attempt)


def get_reinvested_amount(user_id, exchange_id, symbol, initial_amount):
    profit = users_reinvested_profits.get(user_id, {}).get(exchange_id, {}).get(symbol, 0.0)
    reinvest_factor = 1 + (profit / 100)  # Reinvertir el 100% de las ganancias
    return initial_amount * reinvest_factor


async def get_compound_portion(user_id, exchange_id, symbol, base_capital, total_orders):
    """
    Calcula el capital por orden para la grilla compound respetando el capital inicial + ganancias controladas.
    """
    try:
        symbol_config = get_symbol_config(user_id, symbol)
        if not symbol_config:
            logging.error(f"Usuario {user_id}: No se encontró configuración para {symbol}")
            return base_capital / max(1, total_orders)

        # Obtener y validar initial_capital
        initial_capital = symbol_config.get('initial_capital', 5000.0)
        if not isinstance(initial_capital, (int, float)) or initial_capital <= 0:
            initial_capital = 5000.0
            logging.warning(f"Usuario {user_id}: initial_capital inválido para {symbol}, usando 5000.0")

        # Contar órdenes con validación robusta
        buy_orders_total = 0
        try:
            # Verificar que la estructura existe
            if (user_id in users_open_orders and
                    exchange_id in users_open_orders[user_id] and
                    symbol in users_open_orders[user_id][exchange_id]):
                # Sumar con validación individual
                for o in users_open_orders[user_id][exchange_id][symbol]:
                    if isinstance(o, dict) and o.get('side') == 'buy' and o.get('status') == 'open':
                        amount = float(o.get('amount', 0))
                        price = float(o.get('price', 0))
                        if amount > 0 and price > 0:
                            buy_orders_total += amount * price
        except Exception as e:
            logging.error(f"Usuario {user_id}: Error al calcular buy_orders_total: {e}")
            buy_orders_total = 0

        # Calcular órdenes de venta pendientes con validación
        sell_orders_total = 0
        try:
            # Verificar que la estructura existe
            if (user_id in users_pending_sells and
                    exchange_id in users_pending_sells[user_id] and
                    symbol in users_pending_sells[user_id][exchange_id]):
                # Sumar con validación individual
                for o in users_pending_sells[user_id][exchange_id][symbol]:
                    if isinstance(o, dict) and o.get('status') == 'open':
                        amount = float(o.get('amount', 0))
                        price = float(o.get('price', 0))
                        if amount > 0 and price > 0:
                            sell_orders_total += amount * price
        except Exception as e:
            logging.error(f"Usuario {user_id}: Error al calcular sell_orders_total: {e}")
            sell_orders_total = 0

        # Total de capital usado por el token
        token_orders_total = buy_orders_total + sell_orders_total

        # Obtener parámetros configurables con valores por defecto seguros
        reinvestment_pct = float(symbol_config.get('reinvestment_percentage', 75.0))
        max_reinvestment_pct = float(symbol_config.get('max_reinvestment_pct', 50.0))
        reserve_pct = float(symbol_config.get('reserve_percentage', 20.0)) / 100.0

        # Validaciones de configuración con valores por defecto
        if not isinstance(reinvestment_pct, (int, float)) or reinvestment_pct <= 0 or reinvestment_pct > 100:
            reinvestment_pct = 75.0
            logging.warning(f"Usuario {user_id}: reinvestment_pct inválido para {symbol}, usando 75%")

        if not isinstance(max_reinvestment_pct,
                          (int, float)) or max_reinvestment_pct <= 0 or max_reinvestment_pct > 100:
            max_reinvestment_pct = 50.0
            logging.warning(f"Usuario {user_id}: max_reinvestment_pct inválido para {symbol}, usando 50%")

        if not isinstance(reserve_pct, float) or reserve_pct < 0 or reserve_pct >= 1:
            reserve_pct = 0.2
            logging.warning(f"Usuario {user_id}: reserve_pct inválido para {symbol}, usando 20%")

        # Validar total_orders
        if not isinstance(total_orders, int) or total_orders <= 0:
            total_orders = 20
            logging.warning(f"Usuario {user_id}: total_orders inválido para {symbol}, usando 20")

        # Capital base disponible (menos reserva)
        capital_after_reserve = initial_capital * (1 - reserve_pct)
        base_portion = capital_after_reserve / total_orders

        # Obtener y validar ganancias acumuladas con seguridad
        current_profit_pct = 0.0
        if (user_id in users_reinvested_profits and
                exchange_id in users_reinvested_profits[user_id] and
                symbol in users_reinvested_profits[user_id][exchange_id]):
            current_profit_pct = float(users_reinvested_profits[user_id][exchange_id][symbol])

        accumulated_profit = min(current_profit_pct, max_reinvestment_pct)

        # Calcular monto total de ganancia disponible para reinversión
        total_profit_amount = capital_after_reserve * (accumulated_profit / 100)
        reinvestible_profit = total_profit_amount * (reinvestment_pct / 100)
        profit_portion = reinvestible_profit / total_orders

        # Verificar límites del mercado
        exchange = users_exchanges[user_id][exchange_id]
        market = exchange.markets.get(symbol, {})
        min_notional = float(market.get('limits', {}).get('cost', {}).get('min', 0) or 0)

        # Calcular monto final por orden
        final_amount = base_portion + profit_portion
        final_amount = max(final_amount, min_notional)

        # Capital máximo permitido para este token
        max_token_capital = capital_after_reserve + (capital_after_reserve * max_reinvestment_pct / 100)

        # Calcular remaining_capital con seguridad
        remaining_capital = max(0, max_token_capital - token_orders_total)

        # Verificar que no exceda el capital usado por este token
        if token_orders_total + (final_amount * total_orders) > max_token_capital:
            final_amount = remaining_capital / max(1, total_orders)
            logging.warning(
                f"Usuario {user_id}: [compound] Ajuste por exceder capital máximo del token:"
                f"\n - Capital máximo del token: {max_token_capital:.4f}"
                f"\n - Capital en uso del token: {token_orders_total:.4f}"
                f"\n - Capital restante: {remaining_capital:.4f}"
                f"\n - Ajustado a: {final_amount:.4f} por orden"
            )

        # Verificación con balance real de USDT
        try:
            balance = await exchange.fetch_balance()
            available_usdt = float(balance.get('USDT', {}).get('free', 0))
        except Exception as e:
            logging.error(f"Usuario {user_id}: Error al obtener balance: {e}")
            available_usdt = remaining_capital  # Usar remaining_capital como fallback

        # Garantizar que available_usdt sea positivo
        available_usdt = max(0, available_usdt)

        # Calcular max_new_order con seguridad para evitar divisiones por cero
        if total_orders > 0:
            max_new_order = min(remaining_capital, available_usdt) / total_orders
        else:
            max_new_order = min(remaining_capital, available_usdt)

        # Verificar que final_amount sea positivo
        final_amount = max(min(final_amount, max_new_order), 0.1)  # Mínimo 0.1 USDT por orden

        logging.info(
            f"Usuario {user_id}: [compound] Desglose de capital para {symbol}:"
            f"\n - Capital inicial configurado: {initial_capital:.4f}"
            f"\n - Capital operativo (-{reserve_pct * 100}% reserva): {capital_after_reserve:.4f}"
            f"\n - Capital máximo del token: {max_token_capital:.4f}"
            f"\n - Capital en uso por el token: {token_orders_total:.4f}"
            f"\n - Capital disponible del token: {remaining_capital:.4f}"
            f"\n - Ganancia acumulada: {accumulated_profit:.2f}%"
            f"\n - Ganancia total disponible: {total_profit_amount:.4f}"
            f"\n - Porcentaje a reinvertir: {reinvestment_pct:.2f}%"
            f"\n - Monto reinvertible: {reinvestible_profit:.4f}"
            f"\n - Balance USDT disponible: {available_usdt:.4f}"
            f"\n - Porción base por orden: {base_portion:.4f}"
            f"\n - Porción de ganancia por orden: {profit_portion:.4f}"
            f"\n - Monto final por orden: {final_amount:.4f}"
            f"\n - Asignación total planeada: {final_amount * total_orders:.4f}"
        )

        return final_amount

    except Exception as e:
        logging.error(f"Usuario {user_id}: Error en get_compound_portion: {e}", exc_info=True)
        # En caso de error, retornar un valor seguro
        return base_capital / max(1, total_orders)

async def process_symbol_reinvest_strategy(user_id, symbol_config, exchange_id):
    symbol = symbol_config['symbol']
    initial_amount = symbol_config['trade_amount']
    strategy = symbol_config.get('strategy', 'strategy2')

    if not validate_symbol_config(user_id, symbol_config, exchange_id):
        return
    logging.info(f"Usuario {user_id}: Iniciando procesamiento de {symbol} en {exchange_id} con estrategia '{strategy}'")

    model = await initialize_model(user_id, symbol, exchange_id)
    if not model:
        return

    # Inicializar reinversión si no existe
    if user_id not in users_reinvested_profits:
        users_reinvested_profits[user_id] = {}
    if exchange_id not in users_reinvested_profits[user_id]:
        users_reinvested_profits[user_id][exchange_id] = {}
    if symbol not in users_reinvested_profits[user_id][exchange_id]:
        users_reinvested_profits[user_id][exchange_id][symbol] = 0.0  # Inicializar con float

    last_check_time, last_cleanup_time, last_audit_time = 0, 0, 0
    audit_interval = 30  # Auditoría cada 5 minutos

    while users_exchange_running_status[user_id].get(exchange_id, False):
        try:
            current_time = time.time()

            # Realizar tareas periódicas cada intervalo de tiempo
            if current_time - last_check_time >= 10:
                await manage_open_buy_orders(user_id, exchange_id, symbol, symbol_config['order_expiration'],
                                             symbol_config['take_profit'])
                await update_pending_sells(user_id, exchange_id, symbol)
                await check_filled_sell_orders(user_id, exchange_id, symbol)
                last_check_time = current_time

            if current_time - last_cleanup_time >= 3600:  # Limpieza cada hora
                await clean_old_orders(user_id, exchange_id, symbol)
                last_cleanup_time = current_time

            # Auditoría periódica de órdenes
            if current_time - last_audit_time >= audit_interval:
                await audit_orders(user_id, exchange_id, symbol, symbol_config)
                last_audit_time = current_time

            # Actualizar precios de mercado
            market_prices_data = await get_market_prices_async(user_id, exchange_id)
            market_price = market_prices_data.get(symbol)
            logging.info(f"Usuario {user_id}: Precio de mercado para {symbol} en {exchange_id}: {market_price}")

            if market_price is None:
                await asyncio.sleep(10)
                continue

            # Calcular la pérdida diaria
            await calculate_daily_loss(user_id, symbol, exchange_id)
            daily_loss = users_daily_losses[user_id][exchange_id][symbol]
            logging.info(f"Usuario {user_id}: Pérdida diaria actual para {symbol} en {exchange_id}: {daily_loss}%")

            # Gestionar la reactivación del símbolo si está inactivo
            await manage_symbol_reactivation(user_id, symbol, exchange_id, market_price, symbol_config)

            if not should_continue_processing(user_id, exchange_id, symbol):
                logging.info(f"Usuario {user_id}: El símbolo {symbol} está inactivo en {exchange_id}")
                await asyncio.sleep(10)
                continue

            # Detectar caídas repentinas
            sudden_drop = await detect_sudden_drop(user_id, symbol, exchange_id, threshold_percentage=2,
                                                   time_period_minutes=15)
            if sudden_drop:
                users_active_symbols[user_id][exchange_id][symbol] = False
                logging.info(
                    f"Usuario {user_id}: Trading detenido para {symbol} en {exchange_id} debido a una caída repentina del precio"
                )
                users_reactivation_thresholds[user_id][exchange_id][symbol] = market_price * 1.01
                await asyncio.sleep(60)
                continue

            # Obtener los datos OHLCV más recientes
            ohlcv_data = await fetch_latest_ohlcv(user_id, symbol, exchange_id)
            if ohlcv_data.empty:
                await asyncio.sleep(10)
                continue

            # Predecir el próximo precio
            predicted_price = predict_next_price(user_id, model, symbol, exchange_id, ohlcv_data)
            logging.info(f"Usuario {user_id}: Precio predicho para {symbol} en {exchange_id}: {predicted_price}")

            # Decisión de trading basada en la predicción
            await process_trading_decision(user_id, predicted_price, market_price, symbol_config, exchange_id, symbol)

            # Gestionar la pérdida diaria y posible desactivación
            await manage_daily_loss(user_id, symbol, exchange_id, market_price, symbol_config)

            # Auditoría de órdenes
            await audit_orders(user_id, exchange_id, symbol, symbol_config)

            # (Opcional) Si quieres seguir teniendo una “compra extra” SOLO cuando
            # reinvested_amount sea > initial_amount, deja este bloque.
            # De lo contrario, coméntalo/elimínalo.
            reinvested_amount = get_reinvested_amount(user_id, exchange_id, symbol, initial_amount)
            if reinvested_amount > initial_amount:
                logging.info(
                    f"Usuario {user_id}: Reinvirtiendo ganancias. Monto de operación ajustado a {reinvested_amount}")
                await place_buy_order(
                    user_id,
                    symbol,
                    reinvested_amount,
                    predicted_price,
                    exchange_id,
                    symbol_config['order_expiration'],
                    symbol_config
                )
                # Restablecer las ganancias reinvertidas después de usarlas
                users_reinvested_profits[user_id][exchange_id][symbol] = 0.0
                logging.info(
                    f"Usuario {user_id}: Ganancias reinvertidas restablecidas a 0 para {symbol} en {exchange_id}")

            await asyncio.sleep(1)

        except Exception as e:
            logging.error(f"Usuario {user_id}: Error en el procesamiento de {symbol} en {exchange_id}: {e}",
                          exc_info=True)
            await asyncio.sleep(10)


async def wait_for_order_execution(user_id, order_id, symbol, exchange_id, timeout):
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            order = await users_exchanges[user_id][exchange_id].fetch_order(order_id, symbol)
            logging.info(f"Usuario {user_id}: Verificando estado de orden {order_id}: {order['status']}")
            if order['status'] == 'closed':
                return order
            elif order['status'] == 'canceled':
                logging.info(f"Usuario {user_id}: Orden {order_id} fue cancelada externamente")
                return None
            await asyncio.sleep(5)
        except Exception as e:
            logging.error(f"Usuario {user_id}: Error al verificar el estado de la orden {order_id}: {e}")
            await asyncio.sleep(5)

    logging.info(f"Usuario {user_id}: Timeout alcanzado para la orden {order_id}. Intentando cancelar.")
    try:
        cancel_result = await cancel_order_async(user_id, order_id, symbol, exchange_id)
        if cancel_result:
            logging.info(f"Usuario {user_id}: Orden {order_id} cancelada por timeout")
        else:
            logging.warning(f"Usuario {user_id}: No se pudo cancelar la orden {order_id} por timeout")
    except Exception as e:
        logging.error(f"Usuario {user_id}: Error al cancelar la orden {order_id} por timeout: {e}")
    return None


async def update_pending_sells(user_id, exchange_id, symbol):
    try:
        open_sell_orders = await get_open_sell_orders(user_id, exchange_id, symbol)
        users_pending_sells[user_id][exchange_id][symbol] = [
            {
                'id': order['id'],
                'placed_time': order['timestamp'] / 1000 if 'timestamp' in order else time.time(),
                'side': 'sell',
                'amount': order['amount'],
                'price': order['price'],
                'status': order['status']
            }
            for order in open_sell_orders
        ]
        logging.info(
            f"Usuario {user_id}: Órdenes de venta pendientes actualizadas para {symbol} en {exchange_id}: {len(users_pending_sells[user_id][exchange_id][symbol])}")
    except Exception as e:
        logging.error(
            f"Usuario {user_id}: Error al actualizar órdenes de venta pendientes para {symbol} en {exchange_id}: {e}")


async def check_filled_sell_orders(user_id, exchange_id, symbol):
    try:
        exchange = users_exchanges[user_id][exchange_id]
        pending_sells_copy = users_pending_sells[user_id][exchange_id][symbol][:]

        for sell_order_info in pending_sells_copy:
            order_id = sell_order_info['id']
            order = await exchange.fetch_order(order_id, symbol)

            if order['status'] == 'closed':
                logging.info(
                    f"Usuario {user_id}: Orden de venta {order_id} para {symbol} en {exchange_id} ha sido ejecutada"
                )

                # En lugar de usar 'order.get("buy_order_id")', buscamos el buy_order_id en la estructura local
                local_sell_order = users_order_trackers[user_id].sell_orders[exchange_id][symbol].get(order_id)
                if not local_sell_order:
                    logging.error(
                        f"Usuario {user_id}: No se encontró la orden de venta local {order_id} para {symbol}. "
                        "Imposible obtener buy_order_id."
                    )
                    # Removemos de pending_sells para evitar loops
                    users_pending_sells[user_id][exchange_id][symbol].remove(sell_order_info)
                    continue

                buy_order_id = local_sell_order['buy_order_id']

                # Llamamos a process_sell_order con el buy_order_id correcto
                await process_sell_order(
                    user_id,
                    exchange_id,
                    symbol,
                    buy_order_id,  # <-- Campo recuperado de la orden local
                    order
                )

                # Remover de la lista de ventas pendientes
                users_pending_sells[user_id][exchange_id][symbol].remove(sell_order_info)

            elif order['status'] == 'canceled':
                logging.info(
                    f"Usuario {user_id}: Orden de venta {order_id} para {symbol} en {exchange_id} ha sido cancelada"
                )
                # Remover de la lista de ventas pendientes
                users_pending_sells[user_id][exchange_id][symbol].remove(sell_order_info)
            else:
                logging.info(
                    f"Usuario {user_id}: Orden de venta {order_id} para {symbol} en {exchange_id} aún no ejecutada"
                )

    except Exception as e:
        logging.error(
            f"Usuario {user_id}: Error al verificar órdenes de venta ejecutadas para {symbol} en {exchange_id}: {e}"
        )


async def cancel_order_async(user_id, order_id, symbol, exchange_id):
    try:
        # 1) Intentar cancelar en el exchange
        await users_exchanges[user_id][exchange_id].cancel_order(order_id, symbol)
        logging.info(f"Usuario {user_id}: Orden cancelada: {order_id} para {symbol} en {exchange_id}")
    except ccxt.OrderNotFound:
        logging.info(
            f"Usuario {user_id}: Orden {order_id} no encontrada al intentar cancelar. "
            f"Posiblemente ya ejecutada o cancelada."
        )
    except Exception as e:
        logging.error(f"Usuario {user_id}: Error al cancelar la orden {order_id} para {symbol} en {exchange_id}: {e}")

    # 2) Averiguar si la orden era buy o sell, buscando en las listas locales
    local_side = None
    open_orders_list = users_open_orders[user_id][exchange_id][symbol]
    pending_sells_list = users_pending_sells[user_id][exchange_id][symbol]

    for o in open_orders_list:
        if o['id'] == order_id:
            local_side = o['side']
            break

    if not local_side:
        for o in pending_sells_list:
            if o['id'] == order_id:
                local_side = o['side']
                break

    # 3) Remover la orden de las estructuras locales
    open_orders_list[:] = [o for o in open_orders_list if o['id'] != order_id]
    pending_sells_list[:] = [o for o in pending_sells_list if o['id'] != order_id]

    # 4) Actualizar el status en el OrderTracker:
    #    – si encontramos el side, actualizamos sólo en la parte correspondiente.
    #    – si no encontramos nada, llamamos a ambos (caso fallback).
    if local_side == 'buy':
        users_order_trackers[user_id].update_order_status(exchange_id, symbol, order_id, 'canceled', is_buy=True)
    elif local_side == 'sell':
        users_order_trackers[user_id].update_order_status(exchange_id, symbol, order_id, 'canceled', is_buy=False)
    else:
        # fallback por si no se halló en ninguna lista
        users_order_trackers[user_id].update_order_status(exchange_id, symbol, order_id, 'canceled', is_buy=True)
        users_order_trackers[user_id].update_order_status(exchange_id, symbol, order_id, 'canceled', is_buy=False)

    logging.info(
        f"Usuario {user_id}: Orden {order_id} marcada como 'canceled' y removida de las listas locales."
    )

async def initialize_exchanges(user_id):
    for exchange_id, creds in users_exchanges_config[user_id].items():
        if creds.get('active', False):
            try:
                await initialize_exchange(user_id, exchange_id)
            except Exception as e:
                logging.error(f"Usuario {user_id}: Error al inicializar {exchange_id}: {e}")


async def initialize_exchange(user_id, exchange_id, max_retries=3):
    creds = users_exchanges_config[user_id][exchange_id]
    retries = 0

    while retries < max_retries:
        if creds.get('active', False):
            try:
                exchange_class = getattr(ccxt_async, creds['name'])
                exchange_params = {
                    'apiKey': creds['api_key'],
                    'secret': creds['secret'],
                    'enableRateLimit': True
                }
                if 'password' in creds and creds['password']:
                    exchange_params['password'] = creds['password']
                users_exchanges[user_id][exchange_id] = exchange_class(exchange_params)
                await users_exchanges[user_id][exchange_id].load_markets()
                users_connection_status[user_id][exchange_id] = 'Connected'
                users_exchange_running_status[user_id][exchange_id] = True
                logging.info(f"Usuario {user_id}: Exchange {exchange_id} conectado exitosamente.")
                await load_pending_orders(user_id, exchange_id)
                return
            except Exception as e:
                retries += 1
                logging.error(
                    f"Usuario {user_id}: Error al inicializar el exchange {exchange_id}: {e}. Reintento {retries} de {max_retries}")
                users_connection_status[user_id][exchange_id] = 'Disconnected'
                users_exchange_running_status[user_id][exchange_id] = False
                await asyncio.sleep(5)

    logging.error(
        f"Usuario {user_id}: No se pudo conectar el exchange {exchange_id} después de {max_retries} intentos.")


async def load_pending_orders(user_id, exchange_id):
    exchange = users_exchanges[user_id][exchange_id]
    for symbol in users_exchanges_config[user_id][exchange_id]['symbols']:
        try:
            open_sell_orders = await get_open_sell_orders(user_id, exchange_id, symbol)
            users_pending_sells[user_id][exchange_id][symbol] = [
                {
                    'id': order['id'],
                    'placed_time': order.get('timestamp', time.time()) / 1000,
                    'side': 'sell',
                    'amount': order['amount'],
                    'price': order['price'],
                    'status': order['status']
                }
                for order in open_sell_orders
            ]
            logging.info(
                f"Usuario {user_id}: Cargadas {len(open_sell_orders)} órdenes de venta pendientes para {symbol} en {exchange_id}")
        except Exception as e:
            logging.error(f"Usuario {user_id}: Error al cargar órdenes pendientes para {symbol} en {exchange_id}: {e}")


async def reconnect_exchanges(user_id):
    while True:
        for exchange_id in users_exchanges_config[user_id].keys():
            if users_connection_status[user_id][exchange_id] == 'Disconnected':
                try:
                    await initialize_exchange(user_id, exchange_id)
                except Exception as e:
                    logging.error(f"Usuario {user_id}: Error al reconectar el exchange {exchange_id}: {e}")
        await asyncio.sleep(60)


async def handle_command(user_id, command):
    parts = command.strip().split()
    action = parts[0].lower()

    if action == 'start':
        if len(parts) > 1:
            await start_all_exchanges(user_id, ','.join(parts[1:]))
        else:
            await start_all_exchanges(user_id)

    elif action == 'watch':
        await watch_mode(user_id)

    elif action == 'stop':
        await stop_all_exchanges(user_id)

    elif action == 'status':
        show_status(user_id)

    elif action == 'add_exchange':
        add_exchange(user_id, parts[1:])

    elif action == 'edit_exchange':
        edit_exchange(user_id, parts[1:])

    elif action == 'delete_exchange':
        delete_exchange(user_id, parts[1:])

    elif action == 'add_token':
        if len(parts) < 12:
            logging.error(f"Usuario {user_id}: Faltan parámetros para el comando add_token.")
            print(
                "Uso: add_token <exchange_id> <symbol> <spread> <take_profit> <trade_amount> <max_orders> <order_expiration> <daily_loss_max> <max_sell_orders> <reactivation_threshold> <strategy>")
        else:
            token_data = {
                'exchange_id': parts[1],
                'symbol': parts[2],
                'spread': parts[3],
                'take_profit': parts[4],
                'trade_amount': parts[5],
                'max_orders': parts[6],
                'order_expiration': parts[7],
                'daily_loss_max': parts[8],
                'max_sell_orders': parts[9],
                'reactivation_threshold': parts[10],
                'strategy': parts[11]
            }
            result = add_token(user_id, token_data)
            if result:
                logging.info(f"Usuario {user_id}: {result}")
                print(result)

    elif action == 'edit_token':
        if len(parts) < 14:
            logging.error(f"Usuario {user_id}: Faltan parámetros para el comando edit_token.")
            print(
                "Uso: edit_token <exchange_id> <old_symbol> <new_symbol> <spread> <take_profit> <trade_amount> <max_orders> <order_expiration> <daily_loss_max> <max_sell_orders> <reactivation_threshold> <strategy> <exchanges_comma_separated>")
        else:
            token_data = {
                'exchange_id': parts[1],
                'old_symbol': parts[2],
                'new_symbol': parts[3],
                'spread': parts[4],
                'take_profit': parts[5],
                'trade_amount': parts[6],
                'max_orders': parts[7],
                'order_expiration': parts[8],
                'daily_loss_max': parts[9],
                'max_sell_orders': parts[10],
                'reactivation_threshold': parts[11],
                'strategy': parts[12],
                'exchanges': parts[13].split(',')
            }
            result = edit_token(user_id, token_data)
            if result:
                logging.info(f"Usuario {user_id}: {result}")
                print(result)

    elif action == 'delete_token':
        # AHORA INVOCAMOS A LA FUNCIÓN ASÍNCRONA CON AWAIT
        if len(parts) < 3:
            logging.error(f"Usuario {user_id}: Faltan parámetros para el comando delete_token.")
            print("Uso: delete_token <exchange_id> <symbol>")
        else:
            result = await delete_token(user_id, parts[1:])
            if result:
                logging.info(f"Usuario {user_id}: {result}")
                print(result)

    elif action == 'show_open_orders':
        show_open_orders(user_id)

    elif action == 'show_pending_sells':
        show_pending_sells(user_id)

    elif action == 'show_profit_loss':
        show_profit_loss(user_id)

    elif action == 'cancel_order':
        if len(parts) < 4:
            logging.error(f"Usuario {user_id}: Faltan parámetros para el comando cancel_order.")
            print("Uso: cancel_order <exchange_id> <symbol> <order_id>")
        else:
            await cancel_order(user_id, parts[1:])

    elif action == 'help':
        show_help()

    elif action == 'reload_config':
        reload_config(user_id)

    elif action == 'show_config':
        show_config(user_id)

    elif action == 'start_exchange':
        if len(parts) > 1:
            await start_single_exchange(user_id, parts[1])
        else:
            logging.error(f"Usuario {user_id}: Falta el ID del exchange. Usa: start_exchange <exchange_id>")

    elif action == 'show_pnl':
        if len(parts) > 1:
            show_pnl(user_id, parts[1])
        else:
            logging.error(f"Usuario {user_id}: Falta el ID del exchange. Usa: show_pnl <exchange_id>")

    elif action == 'toggle_token':
        if len(parts) > 2:
            result = await toggle_token(user_id, parts[1], parts[2])
            logging.info(f"Usuario {user_id}: {result}")
            print(result)
        else:
            logging.error(f"Usuario {user_id}: Faltan parámetros para toggle_token. Usa: toggle_token <exchange_id> <symbol>")

    else:
        logging.info(f"Usuario {user_id}: Comando no reconocido: {command}")
        print("Comando no reconocido. Usa 'help' para ver los comandos disponibles.")


async def start_single_exchange(user_id, exchange_id):
    if exchange_id in users_exchanges_config[user_id]:
        users_exchange_running_status[user_id][exchange_id] = True
        start_exchange_task(user_id, exchange_id)
        update_bot_status(user_id)
        logging.info(f"Usuario {user_id}: Exchange {exchange_id} iniciado")


async def start_all_exchanges(user_id, exchanges_to_start=None):
    if exchanges_to_start is None or exchanges_to_start.lower() == 'todos':
        exchanges_to_start = users_exchanges_config[user_id].keys()
    else:
        exchanges_to_start = [e.strip() for e in exchanges_to_start.split(',')]
    for exchange_id in exchanges_to_start:
        await start_single_exchange(user_id, exchange_id)
    logging.info(f"Usuario {user_id}: Exchanges seleccionados iniciados")


async def stop_all_exchanges(user_id):
    confirmation = input("¿Está seguro de que desea detener todas las exchanges? (s/n): ")
    if confirmation.lower() != 's':
        logging.info(f"Usuario {user_id}: Operación cancelada.")
        return
    for exchange_id in users_exchanges_config[user_id].keys():
        users_exchange_running_status[user_id][exchange_id] = False
    await close_all_open_buy_orders(user_id)
    logging.info(f"Usuario {user_id}: Todas las exchanges detenidas")


def show_status(user_id):
    for exchange_id, status in users_exchange_running_status[user_id].items():
        print(f"{exchange_id}: {'Ejecutando' if status else 'Detenido'}")
        if status:
            for symbol in users_exchanges_config[user_id][exchange_id]['symbols']:
                print(f" {symbol}: {'Activo' if users_active_symbols[user_id][exchange_id][symbol] else 'Inactivo'}")


def add_exchange(user_id, params):
    if len(params) < 4:
        logging.error(
            f"Usuario {user_id}: Faltan parámetros. Usa: add_exchange <id> <name> <api_key> <secret> <password>")
        return "Faltan parámetros. Usa: add_exchange <id> <name> <api_key> <secret> <password>"

    exchange_id = params[0]
    name = params[1].lower()
    api_key = params[2]
    secret = params[3]
    password = params[4] if len(params) > 4 else ''

    if exchange_id in users_exchanges_config[user_id]:
        logging.error(f"Usuario {user_id}: El exchange {exchange_id} ya existe.")
        return f"El exchange {exchange_id} ya existe."

    if not hasattr(ccxt, name):
        logging.error(f"Usuario {user_id}: El nombre del exchange '{name}' no es válido en ccxt.")
        return f"El nombre del exchange '{name}' no es válido."

    users_exchanges_config[user_id][exchange_id] = {
        'name': name,
        'api_key': api_key,
        'secret': secret,
        'password': password,
        'active': False,
        'symbols': []
    }
    logging.info(f"Usuario {user_id}: Exchange '{exchange_id}' agregado correctamente con nombre '{name}'.")
    save_encrypted_config(user_id)
    return None


def edit_exchange(user_id, params):
    if len(params) < 4:
        logging.error(f"Usuario {user_id}: Faltan parámetros. Usa: edit_exchange <id> <api_key> <secret> <password>")
        return

    exchange_id, api_key, secret, password = params[0], params[1], params[2], params[3]
    if exchange_id not in users_exchanges_config[user_id]:
        logging.error(f"Usuario {user_id}: El exchange {exchange_id} no existe.")
        return

    users_exchanges_config[user_id][exchange_id].update({
        'api_key': api_key,
        'secret': secret,
        'password': password,
    })
    logging.info(f"Usuario {user_id}: Exchange {exchange_id} editado correctamente.")
    save_encrypted_config(user_id)


def delete_exchange(user_id, params):
    if len(params) < 1:
        logging.error(f"Usuario {user_id}: Usa: delete_exchange <id>")
        return

    exchange_id = params[0]
    if exchange_id in users_exchanges_config[user_id]:
        for symbol in users_exchanges_config[user_id][exchange_id]['symbols']:
            symbol_entry = next((s for s in users_symbols_config[user_id] if s['symbol'] == symbol), None)
            if symbol_entry and exchange_id in symbol_entry['exchanges']:
                symbol_entry['exchanges'].remove(exchange_id)
            if not symbol_entry['exchanges']:
                users_symbols_config[user_id].remove(symbol_entry)
        del users_exchanges_config[user_id][exchange_id]
        logging.info(f"Usuario {user_id}: Exchange {exchange_id} eliminado.")
        save_encrypted_config(user_id)
    else:
        logging.error(f"Usuario {user_id}: El exchange {exchange_id} no existe.")


def parse_optional_int(value):
    if value in (None, '', 'None'):
        return None
    else:
        try:
            return int(value)
        except ValueError:
            logging.error(f"Valor inválido para conversión a int: {value}")
            return None


def parse_optional_float(value):
    if value in (None, '', 'None'):
        return None
    else:
        try:
            return float(value)
        except ValueError:
            logging.error(f"Valor inválido para conversión a float: {value}")
            return None


def add_token(user_id, token_data):
    import logging

    # 1) Leer la estrategia
    strategy = token_data.get('strategy')
    exchange_id = token_data['exchange_id']
    symbol = token_data['symbol']

    # Verificaciones básicas
    if exchange_id not in users_exchanges_config[user_id]:
        logging.error(f"Usuario {user_id}: El exchange {exchange_id} no existe.")
        return "El exchange especificado no existe."

    valid_strategies = ['strategy1', 'strategy2', 'strategy3', 'strategy4', 'strategy5', 'compound', 'infinity']
    if strategy not in valid_strategies:
        logging.error(f"Usuario {user_id}: Estrategia inválida: {strategy}.")
        return f"Estrategia inválida. Las estrategias válidas son: {', '.join(valid_strategies)}."

    # CRÍTICO: Verificar si ya existe un token con el mismo símbolo en este exchange específico
    for existing_token in users_symbols_config[user_id]:
        if existing_token['symbol'] == symbol and exchange_id in existing_token.get('exchanges', []):
            logging.warning(f"Usuario {user_id}: El token '{symbol}' ya existe en el exchange '{exchange_id}'.")
            return f"El token '{symbol}' ya existe en el exchange '{exchange_id}'."

    # Siempre crear un token nuevo y específico para cada exchange, sin importar si existe en otros
    new_token = {
        'symbol': symbol,
        'daily_loss_max': parse_optional_float(token_data.get('daily_loss_max')),
        'reactivation_threshold': parse_optional_float(token_data.get('reactivation_threshold')),
        'strategy': strategy,
        'exchanges': [exchange_id],  # IMPORTANTE: Siempre solo un exchange
        'active_exchanges': {exchange_id: True}
    }

    # Añadir configuraciones específicas según la estrategia
    if strategy in ['strategy1', 'strategy2', 'strategy4']:
        new_token.update({
            'spread': parse_optional_float(token_data.get('spread')),
            'take_profit': parse_optional_float(token_data.get('take_profit')),
            'trade_amount': float(token_data['trade_amount']) if 'trade_amount' in token_data else None,
            'max_orders': parse_optional_int(token_data.get('max_orders')),
            'max_sell_orders': parse_optional_int(token_data.get('max_sell_orders')),
            'order_expiration': parse_optional_int(token_data.get('order_expiration'))
        })
    elif strategy == 'compound':
        new_token.update({
            'initial_capital': parse_optional_float(token_data.get('initial_capital')) or 5000.0,
            'spread': parse_optional_float(token_data.get('spread')),
            'take_profit': parse_optional_float(token_data.get('take_profit')),
            'max_orders': parse_optional_int(token_data.get('max_orders')),
            'order_expiration': parse_optional_int(token_data.get('order_expiration')),
            'reinvestment_percentage': parse_optional_float(token_data.get('reinvestment_percentage')) or 75.0,
            'max_reinvestment_pct': parse_optional_float(token_data.get('max_reinvestment_pct')) or 50.0,
            'reserve_percentage': parse_optional_float(token_data.get('reserve_percentage')) or 20.0
        })
    elif strategy == 'infinity':
        new_token.update({
            'total_balance_usdt': parse_optional_float(token_data.get('total_balance_usdt')) or 1000,
            'grid_interval': parse_optional_float(token_data.get('grid_interval')) or 0.002,
            'min_price': parse_optional_float(token_data.get('min_price')) or 8000.0,
            'check_interval': parse_optional_float(token_data.get('check_interval')) or 5,
            'commission': parse_optional_float(token_data.get('commission')) or 0.001,
            'reinvestment_percentage': parse_optional_float(token_data.get('reinvestment_percentage')) or 75.0,
            'max_reinvestment_pct': parse_optional_float(token_data.get('max_reinvestment_pct')) or 50.0,
            'reserve_percentage': parse_optional_float(token_data.get('reserve_percentage')) or 20.0
        })

    # Agregar el token a la configuración y guardarlo
    users_symbols_config[user_id].append(new_token)

    # Agregar el símbolo al exchange
    if symbol not in users_exchanges_config[user_id][exchange_id]['symbols']:
        users_exchanges_config[user_id][exchange_id]['symbols'].append(symbol)

    # Inicializar estructuras para el token
    initialize_symbol(user_id, exchange_id, symbol)

    # Guardar la configuración actualizada
    save_encrypted_config(user_id)

    return f"Token '{symbol}' agregado exitosamente al exchange '{exchange_id}' con estrategia '{strategy}'."


def edit_token(user_id, token_data):
    import logging

    # Datos básicos
    exchange_id = token_data['exchange_id']
    old_symbol = token_data['old_symbol']
    new_symbol = token_data['new_symbol']
    strategy = token_data['strategy']

    # Verificar que el exchange existe
    if exchange_id not in users_exchanges_config[user_id]:
        logging.error(f"Usuario {user_id}: El exchange {exchange_id} no existe.")
        return "El exchange especificado no existe."

    # Verificar que la estrategia es válida
    valid_strategies = ['strategy1', 'strategy2', 'strategy3', 'strategy4', 'strategy5', 'compound', 'infinity']
    if strategy not in valid_strategies:
        logging.error(f"Usuario {user_id}: Estrategia inválida: {strategy}.")
        return f"Estrategia inválida. Las estrategias válidas son: {', '.join(valid_strategies)}."

    # Buscar el token específico para este exchange
    token_to_edit = None
    for token in users_symbols_config[user_id]:
        if token['symbol'] == old_symbol and exchange_id in token.get('exchanges', []):
            token_to_edit = token
            break

    if not token_to_edit:
        logging.error(f"Usuario {user_id}: El token '{old_symbol}' no está asociado con el exchange '{exchange_id}'.")
        return f"El token '{old_symbol}' no está asociado con el exchange '{exchange_id}'."

    # Si estamos cambiando el nombre, verificar que no exista un token con el nuevo nombre en este exchange
    if old_symbol != new_symbol:
        for token in users_symbols_config[user_id]:
            if token['symbol'] == new_symbol and token != token_to_edit and exchange_id in token.get('exchanges', []):
                logging.error(f"Usuario {user_id}: Ya existe un token '{new_symbol}' en el exchange '{exchange_id}'.")
                return f"Ya existe un token '{new_symbol}' en el exchange '{exchange_id}'."

    # Actualizar valores básicos del token
    token_to_edit['symbol'] = new_symbol
    token_to_edit['strategy'] = strategy
    token_to_edit['daily_loss_max'] = parse_optional_float(token_data.get('daily_loss_max'))
    token_to_edit['reactivation_threshold'] = parse_optional_float(token_data.get('reactivation_threshold'))

    # CRÍTICO: Asegurar que el token esté asociado ÚNICAMENTE a este exchange
    token_to_edit['exchanges'] = [exchange_id]
    token_to_edit['active_exchanges'] = {exchange_id: True}

    # Actualizar campos específicos según la estrategia
    if strategy in ['strategy1', 'strategy2', 'strategy4']:
        token_to_edit['spread'] = parse_optional_float(token_data.get('spread'))
        token_to_edit['take_profit'] = parse_optional_float(token_data.get('take_profit'))
        token_to_edit['trade_amount'] = float(token_data['trade_amount']) if 'trade_amount' in token_data else None
        token_to_edit['max_orders'] = parse_optional_int(token_data.get('max_orders'))
        token_to_edit['max_sell_orders'] = parse_optional_int(token_data.get('max_sell_orders'))
        token_to_edit['order_expiration'] = parse_optional_int(token_data.get('order_expiration'))

        # Eliminar campos de otras estrategias
        for field in ['initial_capital', 'reinvestment_percentage', 'max_reinvestment_pct',
                      'reserve_percentage', 'total_balance_usdt', 'grid_interval',
                      'min_price', 'check_interval', 'commission']:
            if field in token_to_edit:
                token_to_edit.pop(field)

    elif strategy == 'compound':
        token_to_edit['initial_capital'] = parse_optional_float(token_data.get('initial_capital')) or 5000.0
        token_to_edit['spread'] = parse_optional_float(token_data.get('spread'))
        token_to_edit['take_profit'] = parse_optional_float(token_data.get('take_profit'))
        token_to_edit['max_orders'] = parse_optional_int(token_data.get('max_orders'))
        token_to_edit['order_expiration'] = parse_optional_int(token_data.get('order_expiration'))
        token_to_edit['reinvestment_percentage'] = parse_optional_float(
            token_data.get('reinvestment_percentage')) or 75.0
        token_to_edit['max_reinvestment_pct'] = parse_optional_float(token_data.get('max_reinvestment_pct')) or 50.0
        token_to_edit['reserve_percentage'] = parse_optional_float(token_data.get('reserve_percentage')) or 20.0

        # Eliminar campos de infinity
        for field in ['total_balance_usdt', 'grid_interval', 'min_price', 'check_interval', 'commission']:
            if field in token_to_edit:
                token_to_edit.pop(field)

    elif strategy == 'infinity':
        token_to_edit['total_balance_usdt'] = parse_optional_float(token_data.get('total_balance_usdt')) or 1000
        token_to_edit['grid_interval'] = parse_optional_float(token_data.get('grid_interval')) or 0.002
        token_to_edit['min_price'] = parse_optional_float(token_data.get('min_price')) or 8000.0
        token_to_edit['check_interval'] = parse_optional_float(token_data.get('check_interval')) or 5
        token_to_edit['commission'] = parse_optional_float(token_data.get('commission')) or 0.001
        token_to_edit['reinvestment_percentage'] = parse_optional_float(
            token_data.get('reinvestment_percentage')) or 75.0
        token_to_edit['max_reinvestment_pct'] = parse_optional_float(token_data.get('max_reinvestment_pct')) or 50.0
        token_to_edit['reserve_percentage'] = parse_optional_float(token_data.get('reserve_percentage')) or 20.0

        # Eliminar campos de compound y strategy1/2/4
        for field in ['initial_capital', 'trade_amount', 'max_sell_orders']:
            if field in token_to_edit:
                token_to_edit.pop(field)

    # Actualizar la lista de símbolos del exchange si el nombre cambió
    if old_symbol != new_symbol:
        if old_symbol in users_exchanges_config[user_id][exchange_id]['symbols']:
            users_exchanges_config[user_id][exchange_id]['symbols'].remove(old_symbol)

        if new_symbol not in users_exchanges_config[user_id][exchange_id]['symbols']:
            users_exchanges_config[user_id][exchange_id]['symbols'].append(new_symbol)

    # Guardar la configuración actualizada
    save_encrypted_config(user_id)

    return f"Token '{old_symbol}' editado exitosamente a '{new_symbol}' en el exchange '{exchange_id}' con estrategia '{strategy}'."

#####################################################################
# 1) FUNCIÓN QUE REALIZA LA LIMPIEZA PROFUNDA DEL TOKEN
#####################################################################
async def delete_token_completamente(user_id, exchange_id, symbol):
    # Detener la tarea del token si está corriendo
    if user_id in users_token_running_status:
        if exchange_id in users_token_running_status[user_id]:
            if symbol in users_token_running_status[user_id][exchange_id]:
                if users_token_running_status[user_id][exchange_id][symbol]:
                    await stop_symbol_task(user_id, exchange_id, symbol)

    # Elimina el token de TODAS las estructuras
    if user_id in users_open_orders:
        users_open_orders[user_id].get(exchange_id, {}).pop(symbol, None)
    if user_id in users_pending_sells:
        users_pending_sells[user_id].get(exchange_id, {}).pop(symbol, None)
    if user_id in users_daily_trades:
        users_daily_trades[user_id].get(exchange_id, {}).pop(symbol, None)
    if user_id in users_market_prices:
        users_market_prices[user_id].get(exchange_id, {}).pop(symbol, None)
    if user_id in users_predicted_prices:
        users_predicted_prices[user_id].get(exchange_id, {}).pop(symbol, None)
    if user_id in users_daily_losses:
        users_daily_losses[user_id].get(exchange_id, {}).pop(symbol, None)
    if user_id in users_profit_loss:
        users_profit_loss[user_id].get(exchange_id, {}).pop(symbol, None)
    if user_id in users_active_symbols:
        users_active_symbols[user_id].get(exchange_id, {}).pop(symbol, None)
    if user_id in users_reactivation_thresholds:
        users_reactivation_thresholds[user_id].get(exchange_id, {}).pop(symbol, None)
    if user_id in users_symbol_tasks:
        users_symbol_tasks[user_id].get(exchange_id, {}).pop(symbol, None)
    if user_id in users_token_running_status:
        users_token_running_status[user_id].get(exchange_id, {}).pop(symbol, None)

    # También limpiamos en el OrderTracker
    if user_id in users_order_trackers:
        tracker = users_order_trackers[user_id]
        if exchange_id in tracker.buy_orders:
            tracker.buy_orders[exchange_id].pop(symbol, None)
        if exchange_id in tracker.sell_orders:
            tracker.sell_orders[exchange_id].pop(symbol, None)

    logging.info(f"Usuario {user_id}: Token '{symbol}' eliminado de todas las estructuras internas.")


async def delete_token(user_id, params):
    if len(params) < 2:
        logging.error(f"Usuario {user_id}: Faltan parámetros. Usa: delete_token <exchange_id> <symbol>")
        return "Faltan parámetros para eliminar el token."

    exchange_id, symbol = params[0], params[1]
    if exchange_id not in users_exchanges_config[user_id]:
        logging.error(f"Usuario {user_id}: El exchange {exchange_id} no existe.")
        return "El exchange especificado no existe."

    # Busca TODOS los tokens con ese símbolo
    matching_tokens = [s for s in users_symbols_config[user_id] if s['symbol'] == symbol]

    if not matching_tokens:
        logging.error(f"Usuario {user_id}: El token '{symbol}' no existe.")
        return f"El token '{symbol}' no existe."

    # Verificar si alguno de los tokens está asociado con este exchange
    token_found = False
    token_to_remove = None

    for token in matching_tokens:
        if exchange_id in token.get('exchanges', []):
            token_found = True
            token_to_remove = token
            break

    if not token_found:
        logging.error(f"Usuario {user_id}: El token '{symbol}' no está asociado con el exchange '{exchange_id}'.")
        return f"El token '{symbol}' no está asociado con el exchange '{exchange_id}'."

    # Eliminar el exchange de la lista de exchanges del token
    token_to_remove['exchanges'].remove(exchange_id)
    if 'active_exchanges' in token_to_remove and exchange_id in token_to_remove['active_exchanges']:
        del token_to_remove['active_exchanges'][exchange_id]

    # 2) Eliminar el símbolo del exchange en la config
    if symbol in users_exchanges_config[user_id][exchange_id]['symbols']:
        users_exchanges_config[user_id][exchange_id]['symbols'].remove(symbol)
        logging.info(f"Usuario {user_id}: Símbolo '{symbol}' eliminado del exchange '{exchange_id}'.")

    # 3) Borrar el token si ya no queda asociado a ningún exchange
    if not token_to_remove['exchanges']:
        users_symbols_config[user_id].remove(token_to_remove)
        logging.info(f"Usuario {user_id}: Token '{symbol}' eliminado completamente (sin exchanges).")

    # Guardar la config
    save_encrypted_config(user_id)

    # 4) Limpiar las estructuras de datos para este token/exchange
    await delete_token_completamente(user_id, exchange_id, symbol)

    return f"Token '{symbol}' eliminado del exchange '{exchange_id}'."


def show_open_orders(user_id):
    for exchange_id, symbols in users_open_orders[user_id].items():
        print(f"Órdenes abiertas para {exchange_id}:")
        for symbol, orders in symbols.items():
            for order in orders:
                print(f" {symbol}: {order}")


def show_pending_sells(user_id):
    for exchange_id, symbols in users_pending_sells[user_id].items():
        print(f"Ventas pendientes para {exchange_id}:")
        for symbol, orders in symbols.items():
            for order in orders:
                print(f" {symbol}: {order}")


def show_profit_loss(user_id):
    for exchange_id, symbols in users_profit_loss[user_id].items():
        print(f"Profit/Loss para {exchange_id}:")
        for symbol, pl in symbols.items():
            print(f" {symbol}: {pl}")


async def cancel_order(user_id, params):
    if len(params) < 3:
        logging.error(f"Usuario {user_id}: Faltan parámetros. Usa: cancel_order <exchange_id> <symbol> <order_id>")
        return "Faltan parámetros para cancelar la orden."

    exchange_id, symbol, order_id = params[0], params[1], params[2]
    await cancel_order_async(user_id, order_id, symbol, exchange_id)


def show_help():
    print("Comandos disponibles:")
    print(" start - Inicia todas las exchanges")
    print(" start_exchange <exchange_id> - Inicia un exchange específico")
    print(" stop - Detiene todas las exchanges")
    print(" status - Muestra el estado actual de las exchanges")
    print(" add_exchange <id> <name> <api_key> <secret> <password> - Agrega un nuevo exchange")
    print(" edit_exchange <id> <api_key> <secret> <password> - Edita un exchange existente")
    print(" delete_exchange <id> - Elimina un exchange")
    print(
        " add_token <exchange_id> <symbol> <spread> <take_profit> <trade_amount> <max_orders> <order_expiration> <daily_loss_max> <max_sell_orders> <reactivation_threshold> <strategy> - Agrega un nuevo token a un exchange")
    print(
        " edit_token <exchange_id> <old_symbol> <new_symbol> <spread> <take_profit> <trade_amount> <max_orders> <order_expiration> <daily_loss_max> <max_sell_orders> <reactivation_threshold> <strategy> <exchanges_comma_separated> - Edita un token existente")
    print(" delete_token <exchange_id> <symbol> - Elimina un token de un exchange")
    print(" show_open_orders - Muestra las órdenes abiertas")
    print(" show_pending_sells - Muestra las ventas pendientes")
    print(" show_profit_loss - Muestra el profit/loss actual")
    print(" cancel_order <exchange_id> <symbol> <order_id> - Cancela una orden específica")
    print(" reload_config - Recarga la configuración desde el archivo")
    print(" show_config - Muestra la configuración actual")
    print("Para la estrategia compound, parámetros adicionales:")
    print(" - reinvestment_percentage: Porcentaje de ganancias a reinvertir (default 75%)")
    print(" - max_reinvestment_pct: Límite máximo de reinversión (default 50%)")
    print(" - reserve_percentage: Porcentaje de saldo a mantener en reserva (default 20%)")
    print(" help - Muestra esta ayuda")


def reinitialize_compound_structures(user_id, exchange_id, symbol):
    """
    Reinicializa estructuras específicas para la estrategia Compound, asegurando
    que no haya interferencia con la estrategia Infinity.
    """
    try:
        # Verificar si es un token compound
        symbol_config = get_symbol_config(user_id, symbol)
        if not symbol_config or symbol_config.get('strategy') != 'compound':
            return

        logging.info(f"Usuario {user_id}: Reinicializando estructuras para token compound {symbol} en {exchange_id}")

        # Inicializar estructuras exclusivas para tokens compound
        if user_id not in users_reinvested_profits:
            users_reinvested_profits[user_id] = {}
        if exchange_id not in users_reinvested_profits[user_id]:
            users_reinvested_profits[user_id][exchange_id] = {}
        if symbol not in users_reinvested_profits[user_id][exchange_id]:
            users_reinvested_profits[user_id][exchange_id][symbol] = 0.0

        # Verificar y corregir max_sell_orders
        if 'max_sell_orders' not in symbol_config or not isinstance(symbol_config['max_sell_orders'], int) or \
                symbol_config['max_sell_orders'] <= 0:
            symbol_config['max_sell_orders'] = 15
            logging.warning(f"Usuario {user_id}: max_sell_orders inválido para {symbol}, configurando en 15")
            save_encrypted_config(user_id)

        # Verificar que las estructuras de órdenes estén limpias
        if user_id not in users_open_orders:
            users_open_orders[user_id] = {}
        if exchange_id not in users_open_orders[user_id]:
            users_open_orders[user_id][exchange_id] = {}
        if symbol not in users_open_orders[user_id][exchange_id]:
            users_open_orders[user_id][exchange_id][symbol] = []

        if user_id not in users_pending_sells:
            users_pending_sells[user_id] = {}
        if exchange_id not in users_pending_sells[user_id]:
            users_pending_sells[user_id][exchange_id] = {}
        if symbol not in users_pending_sells[user_id][exchange_id]:
            users_pending_sells[user_id][exchange_id][symbol] = []

        # Verificar el OrderTracker
        if user_id not in users_order_trackers:
            users_order_trackers[user_id] = OrderTracker()
        if exchange_id not in users_order_trackers[user_id].buy_orders:
            users_order_trackers[user_id].buy_orders[exchange_id] = {}
        if symbol not in users_order_trackers[user_id].buy_orders[exchange_id]:
            users_order_trackers[user_id].buy_orders[exchange_id][symbol] = {}

        if exchange_id not in users_order_trackers[user_id].sell_orders:
            users_order_trackers[user_id].sell_orders[exchange_id] = {}
        if symbol not in users_order_trackers[user_id].sell_orders[exchange_id]:
            users_order_trackers[user_id].sell_orders[exchange_id][symbol] = {}

        logging.info(f"Usuario {user_id}: Estructuras compound reinicializadas para {symbol} en {exchange_id}")

    except Exception as e:
        logging.error(f"Usuario {user_id}: Error al reinicializar estructuras compound para {symbol}: {e}")

def reload_config(user_id):
    load_encrypted_config(user_id)
    logging.info(f"Usuario {user_id}: Configuración recargada.")


def show_config(user_id):
    print(f"Configuración actual para el usuario {user_id}:")
    for exchange_id, config in users_exchanges_config[user_id].items():
        print(f"Exchange: {exchange_id}")
        print(f" Nombre: {config['name']}")
        print(f" API Key: {config['api_key']}")
        print(f" Secret: {'*' * len(config['secret'])}")
        print(f" Símbolos: {', '.join(config['symbols'])}")
        print()


async def shutdown_bot(user_id):
    if user_id in users_exchange_tasks:
        await close_all_open_buy_orders(user_id)

        for exchange_id, task in users_exchange_tasks[user_id].items():
            if not task.done():
                try:
                    task.cancel()
                    await task
                    logging.info(f"Usuario {user_id}: Tarea del exchange {exchange_id} cancelada correctamente.")
                except asyncio.CancelledError:
                    logging.info(f"Usuario {user_id}: Tarea del exchange {exchange_id} ya estaba cancelada.")
                except Exception as e:
                    logging.error(f"Usuario {user_id}: Error al cancelar la tarea del exchange {exchange_id}: {e}")

    if user_id in users_exchanges:
        for exchange_id, exchange in users_exchanges[user_id].items():
            if exchange:
                try:
                    await exchange.close()
                    logging.info(f"Usuario {user_id}: Conexión cerrada correctamente para el exchange {exchange_id}")
                except Exception as e:
                    logging.error(f"Usuario {user_id}: Error cerrando la conexión de exchange {exchange_id}: {e}")

        for exchange_id, exchange in users_exchanges[user_id].items():
            if exchange:
                if exchange.check_required_credentials() and exchange.has['fetchBalance']:
                    logging.error(
                        f"Usuario {user_id}: El exchange {exchange_id} aún parece tener una sesión activa. Revisión adicional recomendada.")
                else:
                    logging.info(
                        f"Usuario {user_id}: Verificación completada: Exchange {exchange_id} cerrado con éxito.")

    logging.warning(f"Usuario {user_id}: Todas las sesiones de cliente han sido cerradas.")


async def close_all_open_buy_orders(user_id):
    logging.info(f"Usuario {user_id}: Cerrando todas las órdenes de compra abiertas...")
    tasks = []
    for exchange_id, symbols in users_open_orders[user_id].items():
        for symbol, orders in symbols.items():
            for order in list(orders):
                if order['side'] == 'buy':
                    tasks.append(cancel_order_async(user_id, order['id'], symbol, exchange_id))
    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                logging.error(f"Usuario {user_id}: Error al cancelar una orden: {result}")
    for exchange_id in users_open_orders[user_id]:
        for symbol in users_open_orders[user_id][exchange_id]:
            users_open_orders[user_id][exchange_id][symbol] = [order for order in
                                                               users_open_orders[user_id][exchange_id][symbol] if
                                                               order['side'] != 'buy']
    logging.info(f"Usuario {user_id}: Proceso de cierre de órdenes de compra abiertas completado")


def clean_duplicate_tokens(user_id):
    """Elimina tokens duplicados de la configuración."""
    logging.info(f"Usuario {user_id}: Iniciando limpieza de tokens duplicados...")

    if user_id not in users_symbols_config:
        logging.warning(f"Usuario {user_id}: No hay tokens configurados.")
        return

    # 1) Rastrear pares únicos (símbolo, exchange)
    token_exchange_pairs = {}  # {(símbolo, exchange): índice_token}

    # 2) Buscar duplicados
    duplicate_indices = set()
    for i, token in enumerate(users_symbols_config[user_id]):
        for ex_id in token.get('exchanges', []):
            pair = (token['symbol'], ex_id)

            if pair in token_exchange_pairs:
                # Este es un duplicado, marcar el token actual para eliminación
                duplicate_indices.add(i)
                logging.warning(f"Usuario {user_id}: Detectado duplicado: {token['symbol']} en {ex_id} (índice {i}).")
            else:
                token_exchange_pairs[pair] = i

    # 3) Eliminar duplicados (de atrás hacia adelante para mantener índices válidos)
    for i in sorted(duplicate_indices, reverse=True):
        try:
            token = users_symbols_config[user_id][i]
            logging.info(f"Usuario {user_id}: Eliminando token duplicado: {token['symbol']} (índice {i})")
            del users_symbols_config[user_id][i]
        except IndexError:
            logging.error(f"Usuario {user_id}: Error al eliminar índice {i}")

    # 4) Reconstruir las listas de símbolos en cada exchange
    for exchange_id in users_exchanges_config[user_id]:
        users_exchanges_config[user_id][exchange_id]['symbols'] = []

    for token in users_symbols_config[user_id]:
        for ex_id in token.get('exchanges', []):
            if ex_id in users_exchanges_config[user_id]:
                if token['symbol'] not in users_exchanges_config[user_id][ex_id]['symbols']:
                    users_exchanges_config[user_id][ex_id]['symbols'].append(token['symbol'])

    # 5) Guardar la configuración limpia
    save_encrypted_config(user_id)
    logging.info(f"Usuario {user_id}: Limpieza de tokens duplicados completada. Configuración guardada.")


async def run_bot(user_id):
    load_encrypted_config(user_id)

    clean_duplicate_tokens(user_id)

    logging.info(
        f"Usuario {user_id}: Configuración cargada. Exchanges configurados: {list(users_exchanges_config[user_id].keys())}")
    logging.info(f"Usuario {user_id}: Símbolos configurados: {[s['symbol'] for s in users_symbols_config[user_id]]}")
    await initialize_exchanges(user_id)
    while True:
        await asyncio.sleep(1)


def start_bot(user_id):
    asyncio.create_task(run_bot(user_id))


def start_exchange_task(user_id, exchange_id):
    if exchange_id not in users_exchange_tasks[user_id]:
        task = asyncio.create_task(run_exchange(user_id, exchange_id))
        users_exchange_tasks[user_id][exchange_id] = task
        logging.info(f"Usuario {user_id}: Tarea para {exchange_id} iniciada.")


async def stop_exchange_task_async(user_id, exchange_id):
    if exchange_id in users_exchange_tasks[user_id]:
        # 1) Cancelar la tarea principal del EXCHANGE
        task = users_exchange_tasks[user_id].pop(exchange_id)
        task.cancel()
        users_exchange_running_status[user_id][exchange_id] = False

        # 2) CANCELAR TODAS LAS TAREAS DE LOS TOKENS DEL EXCHANGE (importante)
        #    Esto marca tokens en 'None' y 'False' => para que al volver a iniciar
        #    el exchange, todos los tokens “activos” inicien sin "ya estaba en ejecución".
        for symbol in list(users_symbol_tasks[user_id][exchange_id].keys()):
            token_task = users_symbol_tasks[user_id][exchange_id][symbol]
            if token_task is not None and not token_task.done():
                token_task.cancel()
            # Forzamos su estado a “NO corriendo”
            users_symbol_tasks[user_id][exchange_id][symbol] = None
            users_token_running_status[user_id][exchange_id][symbol] = False

        # 3) Si ya no queda nada corriendo en ese usuario, poner bot_status=False
        if all(not status for status in users_exchange_running_status[user_id].values()):
            users_bot_status[user_id] = False

        logging.info(f"Usuario {user_id}: Tarea para {exchange_id} detenida.")
        logging.info(f'Usuario {user_id}: Cerrando todas las órdenes de compra abiertas para {exchange_id}...')

        # 4) Cancelar las órdenes de compra abiertas
        cancel_tasks = []
        for symbol, orders in users_open_orders[user_id][exchange_id].items():
            for order in list(orders):
                if order.get('side') == 'buy':
                    cancel_tasks.append(cancel_order_async(user_id, order['id'], symbol, exchange_id))

        if cancel_tasks:
            results = await asyncio.gather(*cancel_tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    logging.error(f"Usuario {user_id}: Error al cancelar una orden en {exchange_id}: {result}")

        # 5) Limpiar la lista local de órdenes de compra
        for symbol in users_open_orders[user_id][exchange_id]:
            users_open_orders[user_id][exchange_id][symbol] = [
                order for order in users_open_orders[user_id][exchange_id][symbol]
                if order.get('side') != 'buy'
            ]

        logging.info(f"Usuario {user_id}: Proceso de cierre de órdenes de compra completado para {exchange_id}.")

        # 6) Registrar el estado actualizado
        update_bot_status(user_id)
        logging.info(f"Usuario {user_id}: Estado del bot actualizado. Activo: {users_bot_status.get(user_id, False)}")
        return True
    else:
        logging.warning(f"Usuario {user_id}: No se encontró tarea para detener en el exchange {exchange_id}")
        return False

async def clear_pending_sell_orders(user_id, exchange_id, symbol):
    try:
        if (user_id in users_pending_sells and
            exchange_id in users_pending_sells[user_id] and
            symbol in users_pending_sells[user_id][exchange_id]):
            pending_orders = list(users_pending_sells[user_id][exchange_id][symbol])
            for order in pending_orders:
                # Obtenemos el status (en minúsculas); si no existe, se asume que es pendiente.
                status = order.get('status', '').lower()
                # Solo se cancelan aquellas órdenes cuyo estado NO sea 'open' ni 'closed'
                if status not in ['open', 'closed']:
                    try:
                        await cancel_order_async(user_id, order['id'], symbol, exchange_id)
                        logging.info(f"Orden de venta pendiente {order['id']} cancelada correctamente.")
                        users_pending_sells[user_id][exchange_id][symbol].remove(order)
                        if (exchange_id in users_order_trackers[user_id].sell_orders and
                            symbol in users_order_trackers[user_id].sell_orders[exchange_id]):
                            users_order_trackers[user_id].sell_orders[exchange_id][symbol].pop(order['id'], None)
                    except Exception as e:
                        logging.error(f"Error al cancelar la orden pendiente {order['id']}: {e}")
                else:
                    logging.info(f"La orden {order['id']} con status '{order.get('status')}' ya está colocada o ejecutada; no se cancela.")
    except Exception as e:
        logging.error(f"Error al borrar órdenes pendientes de venta para {symbol} en {exchange_id}: {e}")
        raise e


async def run_exchange(user_id, exchange_id):
    try:
        await initialize_exchange(user_id, exchange_id)
        exchange = users_exchanges[user_id].get(exchange_id)

        if exchange and users_exchange_running_status[user_id][exchange_id]:
            exchange_symbols = users_exchanges_config[user_id][exchange_id].get('symbols', [])
            logging.info(f"Usuario {user_id}: Símbolos configurados para {exchange_id}: {exchange_symbols}")

            for symbol in exchange_symbols:
                symbol_config = get_symbol_config(user_id, symbol)
                # 1) Verificar si está habilitado (active_exchanges[exchange_id] == True)
                if symbol_config.get('active_exchanges', {}).get(exchange_id, True):
                    # 2) Verificar si NO fue detenido manualmente (runtime == True)
                    if users_token_running_status[user_id][exchange_id][symbol]:
                        await start_symbol_task(user_id, exchange_id, symbol)

            # Mientras el exchange siga "running", quedamos en un loop
            while users_exchange_running_status[user_id][exchange_id]:
                await asyncio.sleep(5)

    except asyncio.CancelledError:
        logging.info(f"Usuario {user_id}: Tarea para {exchange_id} cancelada")
    except Exception as e:
        logging.error(f"Usuario {user_id}: Error en la ejecución de {exchange_id}: {e}")
    finally:
        # Cancelar todas las tasks de tokens de este exchange al cerrar
        for symbol, task in users_symbol_tasks[user_id][exchange_id].items():
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    logging.info(f"Tarea token {symbol} cancelada al finalizar exchange {exchange_id}.")

        logging.info(f"Usuario {user_id}: Tareas para {exchange_id} finalizadas")


async def start_symbol_task(user_id, exchange_id, symbol):
    """
    Inicia la tarea asíncrona para un token específico.
    Retorna True si se inició, False si estaba corriendo o deshabilitado.
    """
    # Verificar si podemos iniciar más tareas
    if not task_limiter.can_start_task(user_id, exchange_id):
        logging.warning(f"Usuario {user_id}: Límite de tareas alcanzado para {exchange_id}")
        return False

    # Asegurar que todas las estructuras están inicializadas
    initialize_symbol(user_id, exchange_id, symbol)

    # Obtener la configuración del símbolo
    symbol_config = get_symbol_config(user_id, symbol)
    if symbol_config and symbol_config.get('strategy') == 'compound':
        # Si es un token compound, reinicializar sus estructuras específicas
        reinitialize_compound_structures(user_id, exchange_id, symbol)
        logging.info(f"Usuario {user_id}: Reinicializadas estructuras específicas de Compound para {symbol}")

    # Si YA existe una tarea, cancelarla primero
    if users_symbol_tasks[user_id][exchange_id][symbol] is not None:
        try:
            current_task = users_symbol_tasks[user_id][exchange_id][symbol]
            if not current_task.done():
                current_task.cancel()
                await asyncio.sleep(1)  # Dar tiempo para que se cancele
                try:
                    await current_task
                except asyncio.CancelledError:
                    pass
        except Exception as e:
            logging.error(f"Error al cancelar tarea existente: {e}")
        users_symbol_tasks[user_id][exchange_id][symbol] = None
        users_token_running_status[user_id][exchange_id][symbol] = False
        await asyncio.sleep(1)  # Esperar un momento antes de reiniciar

    # Verificar si está deshabilitado en config
    symbol_config = get_symbol_config(user_id, symbol)
    if not symbol_config or not symbol_config.get('active_exchanges', {}).get(exchange_id, True):
        logging.warning(f"Token {symbol} en {exchange_id} está deshabilitado, no se puede iniciar.")
        return False

    # Verificar que el exchange esté corriendo
    if not users_exchange_running_status[user_id].get(exchange_id, False):
        logging.warning(f"Exchange {exchange_id} no está en ejecución, no se puede iniciar el token {symbol}.")
        return False

    # Incrementar el contador de tareas
    task_limiter.increment_tasks(user_id, exchange_id)

    try:
        # Marcar runtime=True y crear la tarea
        users_token_running_status[user_id][exchange_id][symbol] = True
        task = asyncio.create_task(process_symbol(user_id, symbol_config, exchange_id))
        users_symbol_tasks[user_id][exchange_id][symbol] = task

        logging.info(f"Usuario {user_id}: Token {symbol} en {exchange_id} iniciado correctamente.")
        return True
    except Exception as e:
        # En caso de error, decrementar el contador
        task_limiter.decrement_tasks(user_id, exchange_id)
        logging.error(f"Error al iniciar tarea para {symbol}: {e}")
        return False


async def stop_symbol_task(user_id, exchange_id, symbol):
    """Detiene la tarea asíncrona de un token (símbolo) específico."""
    task = users_symbol_tasks[user_id][exchange_id].get(symbol)

    if task is None:
        logging.warning(f"Usuario {user_id}: Token {symbol} en {exchange_id} no estaba corriendo.")
        return False

    # 1) Cancelar la tarea del token
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    # 2) Cerrar las órdenes de compra abiertas para ESTE token (igual que en stop_exchange_task_async)
    cancel_tasks = []
    if symbol in users_open_orders[user_id][exchange_id]:
        for order in list(users_open_orders[user_id][exchange_id][symbol]):
            if order.get('side') == 'buy':
                cancel_tasks.append(cancel_order_async(user_id, order['id'], symbol, exchange_id))

    # Ejecutar la cancelación en paralelo
    if cancel_tasks:
        results = await asyncio.gather(*cancel_tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                logging.error(
                    f"Usuario {user_id}: Error al cancelar orden en {exchange_id} (token={symbol}): {result}"
                )

    # 3) Limpiar la lista local de órdenes (descartar las de compra)
    if symbol in users_open_orders[user_id][exchange_id]:
        users_open_orders[user_id][exchange_id][symbol] = [
            o for o in users_open_orders[user_id][exchange_id][symbol]
            if o.get('side') != 'buy'
        ]

    # 4) Marcarlo como detenido
    users_symbol_tasks[user_id][exchange_id][symbol] = None
    users_token_running_status[user_id][exchange_id][symbol] = False

    # 5) Decrementar el contador de tareas
    task_limiter.decrement_tasks(user_id, exchange_id)

    logging.info(
        f"Usuario {user_id}: Token {symbol} en {exchange_id} se ha detenido y las órdenes de compra fueron cerradas.")
    return True

async def watch_mode(user_id):
    try:
        while True:
            os.system('cls' if os.name == 'nt' else 'clear')
            print(f"=== Estado Actual del Bot para el Usuario {user_id} ===")
            for exchange_id, status in users_exchange_running_status[user_id].items():
                print(f"\nExchange: {exchange_id} - {'Activo' if status else 'Inactivo'}")
                if status:
                    for symbol in users_exchanges_config[user_id][exchange_id]['symbols']:
                        price = users_market_prices[user_id].get(exchange_id, {}).get(symbol, 'N/A')
                        prediction = users_predicted_prices[user_id].get(exchange_id, {}).get(symbol, 'N/A')
                        pl = users_profit_loss[user_id].get(exchange_id, {}).get(symbol, 0)
                        print(f" {symbol}: Precio: {price}, Predicción: {prediction}, P/L: {pl}")
            print("\nÓrdenes Abiertas:")
            for exchange_id, symbols in users_open_orders[user_id].items():
                for symbol, orders in symbols.items():
                    for order in orders:
                        print(f" {exchange_id} - {symbol}: {order['side']} {order['amount']} @ {order['price']}")
            print("\nPresione Ctrl+C para salir del modo de monitoreo")
            await asyncio.sleep(5)
    except asyncio.CancelledError:
        logging.info(f"Usuario {user_id}: Saliendo del modo de monitoreo...")
    except KeyboardInterrupt:
        print(f"\nUsuario {user_id}: Saliendo del modo de monitoreo...")


def show_pnl(user_id, exchange_id):
    transactions = load_transactions(user_id, exchange_id)
    total_pnl = 0
    results = []
    for transaction in transactions:
        results.append({
            "symbol": transaction['symbol'],
            "buy_amount": transaction['buy_amount'],
            "buy_price": transaction['buy_price'],
            "sell_amount": transaction['sell_amount'],
            "sell_price": transaction['sell_price'],
            "commission": transaction['commission'],
            "pnl": transaction['pnl'],
        })
        total_pnl += transaction['pnl']
    return {
        "transactions": results,
        "total_pnl": total_pnl
    }


def get_total_pnl(user_id, exchange_id):
    try:
        # Cargar todas las transacciones para este exchange
        transactions = load_transactions(user_id, exchange_id)
        logging.info(f"Usuario {user_id}: Cargadas {len(transactions)} transacciones para {exchange_id}")

        # Calcular el PnL estándar
        standard_pnl = sum(t.get('pnl', 0) for t in transactions)

        # Buscar y sumar el PnL de todos los tokens Infinity
        infinity_pnl = 0
        infinity_tokens = [t for t in users_symbols_config.get(user_id, [])
                           if t.get('strategy') == 'infinity' and exchange_id in t.get('exchanges', [])]

        for token in infinity_tokens:
            symbol = token['symbol']
            # Usar el PnL registrado directamente para Infinity
            token_pnl = users_profit_loss.get(user_id, {}).get(exchange_id, {}).get(symbol, 0)
            infinity_pnl += token_pnl

        # Devolver la suma
        return standard_pnl + infinity_pnl
    except Exception as e:
        logging.error(f"Usuario {user_id}: Error al calcular PNL para {exchange_id}: {str(e)}")
        return 0

async def main():
    try:
        load_users()
        while True:
            action = input("Ingrese 'login' para iniciar sesión o 'register' para registrarse: ").strip().lower()
            if action == 'register':
                user_id = input("Ingrese un nombre de usuario: ").strip()
                password = input("Ingrese una contraseña: ").strip()
                email = input("Ingrese su correo electrónico: ").strip()

                print("Seleccione 2 preguntas de seguridad de las siguientes opciones:")
                for idx, question in enumerate(security_questions, 1):
                    print(f"{idx}. {question}")

                selected_questions = []
                answers = []
                while len(selected_questions) < 2:
                    try:
                        choice = int(input(f"Seleccione la pregunta {len(selected_questions) + 1}: "))
                        if 1 <= choice <= len(security_questions) and security_questions[
                            choice - 1] not in selected_questions:
                            selected_questions.append(security_questions[choice - 1])
                            answer = input(f"Respuesta para '{security_questions[choice - 1]}': ").strip()
                            hashed_answer = hashlib.sha256(answer.encode()).hexdigest()
                            answers.append({'question': security_questions[choice - 1], 'answer': hashed_answer})
                        else:
                            print("Selección inválida o pregunta ya seleccionada. Intente nuevamente.")
                    except ValueError:
                        print("Entrada inválida. Por favor, ingrese el número correspondiente.")

                success, message = register_user(user_id, password, email, answers)
                print(message)
                if success:
                    initialize_structures(user_id)
                    save_encrypted_config(user_id)
            elif action == 'login':
                user_id = input("Ingrese su nombre de usuario: ").strip()
                password = input("Ingrese su contraseña: ").strip()
                if authenticate_user(user_id, password):
                    print(f"Bienvenido, {user_id}!")
                    load_encrypted_config(user_id)
                    initialize_json_files(user_id)
                    await run_bot_for_user(user_id)
                else:
                    print("Credenciales incorrectas.")
            else:
                print("Comando no reconocido.")
    except Exception as e:
        logging.error(f"Error en la ejecución principal: {e}")
    finally:
        for user_id in users:
            asyncio.run(disconnect_exchanges(user_id))
        logging.info("Bot detenido.")


async def disconnect_exchanges(user_id):
    for exchange_id, exchange in users_exchanges[user_id].items():
        try:
            await exchange.close()
            logging.info(f"Usuario {user_id}: Exchange {exchange_id} desconectado correctamente.")
        except Exception as e:
            logging.error(f"Usuario {user_id}: Error al desconectar el exchange {exchange_id}: {str(e)}")


async def run_bot_for_user(user_id):
    try:
        print(f"Iniciando bot para el usuario {user_id}")
        await initialize_exchanges(user_id)
        await start_trading_tasks(user_id)

        while True:
            command = input("Ingrese un comando (o 'exit' para salir): ")
            if command.lower() == 'exit':
                break
            elif command.lower() == 'watch':
                try:
                    await watch_mode(user_id)
                except KeyboardInterrupt:
                    print("\nSaliendo del modo de monitoreo...")
            else:
                await handle_command(user_id, command)
    except Exception as e:
        logging.error(f"Usuario {user_id}: Error en la ejecución del bot: {e}")
    finally:
        await shutdown_bot(user_id)


async def start_trading_tasks(user_id):
    for exchange_id in users_exchanges_config[user_id]:
        start_exchange_task(user_id, exchange_id)


if __name__ == "__main__":
    if not os.path.exists(json_directory):
        os.makedirs(json_directory)
    asyncio.run(main())