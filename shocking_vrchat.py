from typing import List
import asyncio
import yaml, uuid, os, sys, traceback, time, socket, re, json
from threading import Thread
from loguru import logger
import traceback
import copy

from flask import Flask, render_template, redirect, request, jsonify

import srv
from srv.connector.ycy_ble import YCYBLEConnector
from srv.handler.shock_handler import ShockHandler
from srv.handler.machine_handler import TuyaHandler, TuYaConnection

from pythonosc.osc_server import AsyncIOOSCUDPServer
from pythonosc.dispatcher import Dispatcher
from pythonosc.udp_client import SimpleUDPClient

# 全局 BLE 连接器实例
ble_connector: YCYBLEConnector = None
# OSC 输出客户端 (用于向 VRChat 发送设备状态)
osc_client: SimpleUDPClient = None

# 通道时间管理器 (BLE 模式下模拟波形队列)
class ChannelTimeManager:
    """管理每个通道的强度和清除时间 - 模拟波形队列"""
    def __init__(self):
        self.clear_time = {'A': 0, 'B': 0}  # 清除时间
        self.current_strength = {'A': 0, 'B': 0}  # 当前强度
        self._running = False

    async def set_strength_for_duration(self, channel: str, strength: int, duration_ms: int, reset: bool = False):
        """设置强度并在指定时间后自动清除

        Args:
            channel: 通道 A 或 B
            strength: 强度 (0-200)
            duration_ms: 持续时间 (毫秒)
            reset: True=重置队列时间, False=叠加队列时间
        """
        channel = channel.upper()
        now = time.time()
        duration_sec = duration_ms / 1000.0

        if reset:
            # 重置模式：直接覆盖时间
            self.clear_time[channel] = now + duration_sec
        else:
            # 叠加模式：如果当前还有剩余时间，在其基础上增加
            if self.clear_time[channel] > now:
                self.clear_time[channel] += duration_sec
            else:
                self.clear_time[channel] = now + duration_sec

        self.current_strength[channel] = strength

        # 设置强度
        await YCYBLEConnector.broadcast_strength(channel, strength)

    async def clear_check_loop(self):
        """后台任务：检查并清除过期的强度"""
        self._running = True
        while self._running:
            await asyncio.sleep(0.05)  # 50ms 检查间隔
            now = time.time()
            for channel in ['A', 'B']:
                if self.current_strength[channel] > 0 and now > self.clear_time[channel]:
                    await YCYBLEConnector.broadcast_strength(channel, 0)
                    logger.info(f'[TimeManager] Channel {channel}: 队列结束，强度归零')
                    self.current_strength[channel] = 0

    def stop(self):
        self._running = False

# 全局时间管理器
channel_manager = ChannelTimeManager()

app = Flask(__name__)

CONFIG_FILE_VERSION  = 'v0.2'
CONFIG_FILENAME = f'settings-advanced-{CONFIG_FILE_VERSION}.yaml'
CONFIG_FILENAME_BASIC = f'settings-{CONFIG_FILE_VERSION}.yaml'
SETTINGS_BASIC = {
    'dglab3':{
        'channel_a': {
            'avatar_params': [
                '/avatar/parameters/pcs/contact/enterPass',
                '/avatar/parameters/Shock/TouchAreaA',
                '/avatar/parameters/Shock/TouchAreaC',
                '/avatar/parameters/Shock/wildcard/*',
            ],
            'mode': 'distance',
            'strength_limit': 100,
        },
        'channel_b': {
            'avatar_params': [
                '/avatar/parameters/pcs/contact/enterPass',
                '/avatar/parameters/lms-penis-proximityA*',
                '/avatar/parameters/Shock/TouchAreaB',
                '/avatar/parameters/Shock/TouchAreaC',
            ],
            'mode': 'distance',
            'strength_limit': 100,
        }
    },
    'version': CONFIG_FILE_VERSION,
}
SETTINGS = {
    'SERVER_IP': None,
    'ble': {
        'device_address': None,  # 留空则自动扫描
        'scan_timeout': 10.0,
        'strength_limit': 200,
    },
    'dglab3': {
        'channel_a': {
            'mode_config':{
                'shock': {
                    'duration': 2,
                    'wave': '["0A0A0A0A64646464","0A0A0A0A64646464","0A0A0A0A64646464","0A0A0A0A64646464","0A0A0A0A64646464","0A0A0A0A64646464","0A0A0A0A64646464","0A0A0A0A64646464","0A0A0A0A64646464","0A0A0A0A64646464"]',
                },
                'distance': {
                    'freq_ms': 10,
                },
                'trigger_range': {
                    'bottom': 0.0,
                    'top': 1.0,
                },
                'touch': {
                    'freq_ms': 10,
                    'n_derivative': 1, # 0 for distance, 1 for velocity, 2 for acceleration, 3 for jerk
                    'derivative_params': [
                        {
                            "top": 1,
                            "bottom": 0,
                        },
                        {
                            "top": 5,
                            "bottom": 0,
                        },
                        {
                            "top": 50,
                            "bottom": 0,
                        },
                        {
                            "top": 500,
                            "bottom": 0,
                        },
                    ]
                },
            }
        },
        'channel_b': {
            'mode_config':{
                'shock': {
                    'duration': 2,
                    'wave': '["0A0A0A0A64646464","0A0A0A0A64646464","0A0A0A0A64646464","0A0A0A0A64646464","0A0A0A0A64646464","0A0A0A0A64646464","0A0A0A0A64646464","0A0A0A0A64646464","0A0A0A0A64646464","0A0A0A0A64646464"]',
                },
                'distance': {
                    'freq_ms': 10,
                },
                'trigger_range': {
                    'bottom': 0.0,
                    'top': 1.0,
                },
                'touch': {
                    'freq_ms': 10,
                    'n_derivative': 1,
                    'derivative_params': [
                        {
                            "top": 1,
                            "bottom": 0,
                        },
                        {
                            "top": 5,
                            "bottom": 0,
                        },
                        {
                            "top": 50,
                            "bottom": 0,
                        },
                        {
                            "top": 500,
                            "bottom": 0,
                        },
                    ]
                },
            }
        },
    },
    'osc':{
        'listen_host': '127.0.0.1',
        'listen_port': 9001,
        'output_host': '127.0.0.1',
        'output_port': 9000,
        'output_param_prefix': '/avatar/parameters/ShockingVRChat',
        'output_enabled': True,
    },
    'web_server':{
        'listen_host': '127.0.0.1',
        'listen_port': 8800
    },
    'log_level': 'INFO',
    'version': CONFIG_FILE_VERSION,
    'general': {
        'auto_open_qr_web_page': False,  # BLE 模式不需要二维码
        'local_ip_detect': {
            'host': '223.5.5.5',
            'port': 80,
        }
    }
}
SERVER_IP = None

@app.route('/get_ip')
def get_current_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect((SETTINGS['general']['local_ip_detect']['host'], SETTINGS['general']['local_ip_detect']['port']))
    client_ip = s.getsockname()[0]
    s.close()
    return client_ip

@app.route("/")
def web_index():
    return redirect("/status", code=302)

@app.route("/status")
def web_status():
    """显示 BLE 连接状态"""
    return render_template('status.html')

@app.route('/conns')
def get_conns():
    """获取连接状态"""
    global ble_connector
    if ble_connector and ble_connector.connected:
        return f"BLE connected: {ble_connector.device_address}"
    return "BLE not connected"

@app.route('/sendwav')
async def sendwav():
    """测试端点：发送当前选中的波形"""
    strength_limit = SETTINGS['dglab3']['channel_a'].get('strength_limit', 200)
    await YCYBLEConnector.broadcast_wave(channel='A', wavestr=srv.DEFAULT_WAVE, strength_limit=strength_limit)
    return 'OK'

@app.after_request
async def after_request_hook(response):
    if request.args.get('ret') == 'status' and response.status_code == 200:
        response = jsonify(await api_v1_status())
    return response

class ClientNotAllowed(Exception):
    pass

@app.errorhandler(ClientNotAllowed)
def hendle_ClientNotAllowed(e):
    return {
        "error": "Client not allowed."
    }, 401

@app.errorhandler(Exception)
def handle_Exception(e):
    return {
        "error": str(e)
    } , 500

# Disallow (Video)
# User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.72 Safari/537.36\r\n
# User-Agent: NSPlayer/12.00.26100.2314 WMFSDK/12.00.26100.2314\r\n
# Allow (Text/Image)
# User-Agent: UnityPlayer/2022.3.22f1-DWR (UnityWebRequest/1.0, libcurl/8.5.0-DEV)\r\n
def allow_vrchat_only(func):
    async def wrapper(*args, **kwargs):
        ua = request.headers.get('User-Agent')
        if 'UnityPlayer' not in ua:
            raise ClientNotAllowed
        if 'NSPlayer' in ua or 'WMFSDK' in ua:
            raise ClientNotAllowed
        return await func(*args, **kwargs)
    return wrapper

@app.route('/api/v1/status')
async def api_v1_status():
    """完全兼容原版 API 格式"""
    global ble_connector
    devices = []

    if ble_connector and ble_connector.connected:
        strength = ble_connector.strength_data
        # 基于 MAC 地址生成 UUID 格式
        mac = ble_connector.device_address or '00:00:00:00:00:00'
        mac_hex = mac.replace(':', '').lower()
        # 填充为 UUID 格式: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
        device_uuid = f"{mac_hex[:8]}-{mac_hex[8:12] if len(mac_hex) > 8 else '0000'}-4000-8000-{mac_hex.zfill(12)}"

        devices.append({
            "type": 'shock',
            'device': 'coyotev3',
            'attr': {
                'strength': {
                    'A': strength.a if strength else 0,
                    'B': strength.b if strength else 0
                },
                'uuid': device_uuid
            }
        })

    return {
        'healthy': 'ok',
        'devices': devices
    }


@app.route('/api/v1/status/detail')
async def api_v1_status_detail():
    """详细状态 API (扩展)"""
    global ble_connector
    devices = []

    if ble_connector and ble_connector.connected:
        strength = ble_connector.strength_data
        battery = -1
        electrode_a = 'unknown'
        electrode_b = 'unknown'
        try:
            battery = await ble_connector.get_battery()
            electrode_a = await ble_connector.get_electrode_status('A')
            electrode_b = await ble_connector.get_electrode_status('B')
        except Exception:
            pass

        devices.append({
            "type": 'shock',
            'device': 'ycy_ble',
            'attr': {
                'strength_a': strength.a if strength else 0,
                'strength_b': strength.b if strength else 0,
                'uuid': ble_connector.device_address or 'ble-device',
                'battery': battery,
                'electrode_a': electrode_a,
                'electrode_b': electrode_b,
            }
        })

    return {
        'healthy': 'ok',
        'connected': ble_connector.connected if ble_connector else False,
        'devices': devices
    }

@app.route('/api/v1/shock/<channel>/<second>', endpoint='api_v1_shock')
@allow_vrchat_only
async def api_v1_shock(channel, second):
    """BLE 模式下的电击 API - 使用时间管理器"""
    if channel == 'all':
        channels = ['A', 'B']
    else:
        channels = [channel.upper()]
    try:
        second = float(second)
    except Exception:
        logger.warning('[API][shock] Invalid second, set to 1.')
        second = 1.0
    second = min(second, 10.0)
    duration_ms = int(second * 1000)

    # 使用时间管理器设置强度 (reset=True: 重置队列而非叠加)
    for chan in channels:
        config_channel = f'channel_{chan.lower()}'
        strength_limit = SETTINGS['dglab3'][config_channel].get('strength_limit', 200)
        await channel_manager.set_strength_for_duration(chan, strength_limit, duration_ms, reset=True)
        logger.success(f'[API][shock] Channel {chan}: 强度 {strength_limit}, 持续 {second}s (队列重置)')

    return {'result': 'OK'}

@app.route('/api/v1/sendwave/<channel>/<repeat>/<wavedata>', endpoint='api_v1_sendwave')
@allow_vrchat_only
async def api_v1_sendwave(channel, repeat, wavedata):
    """API V1 Sendwave (BLE 模式).

    Keyword arguments:
    channel -- A or B.
    repeat -- repeat times, 1 for 100ms, 1 to 80. Max 80 for json length limit.
    wavedata -- Coyote v3 wave format, eg. 0A0A0A0A64646464.

    BLE 模式: 解析波形强度，设置强度并持续 repeat*100ms
    """
    try:
        channel = channel.upper()
        if channel not in ['A', 'B']:
            raise Exception
    except:
        logger.warning('[API][sendwave] Invalid Channel, set to A.')
        channel = 'A'
    try:
        repeat = int(repeat)
        if repeat > 100 or repeat < 1:
            raise Exception
    except:
        logger.warning('[API][sendwave] Invalid repeat times, set to 10.')
        repeat = 10
    try:
        if not re.match(r'^([0-9A-F]{16})$', wavedata):
            raise Exception
    except:
        logger.warning('[API][sendwave] Invalid wave, set to 0A0A0A0A64646464.')
        wavedata = '0A0A0A0A64646464'

    # 解析波形强度 (最后2个hex字符)
    strength_percent = int(wavedata[-2:], 16)  # 0-100

    # 获取通道的 strength_limit
    config_channel = f'channel_{channel.lower()}'
    strength_limit = SETTINGS['dglab3'][config_channel].get('strength_limit', 200)

    # 计算实际强度
    actual_strength = int(strength_percent * strength_limit / 100)
    duration_ms = repeat * 100

    logger.success(f'[API][sendwave] C:{channel} 强度:{strength_percent}% -> {actual_strength}/{strength_limit}, 持续:{duration_ms}ms')

    # 使用时间管理器 (支持队列叠加)
    await channel_manager.set_strength_for_duration(channel, actual_strength, duration_ms)

    return {'result': 'OK'}

def strip_basic_settings(settings: dict):
    ret = copy.deepcopy(settings)
    for chann in ['channel_a', 'channel_b']:
        del ret['dglab3'][chann]['avatar_params']
        del ret['dglab3'][chann]['mode'] 
        del ret['dglab3'][chann]['strength_limit'] 
    return ret

@app.route('/api/v1/config', methods=['GET', 'HEAD', 'OPTIONS'])
def get_config():
    return {
        'basic': SETTINGS_BASIC,
        'advanced': strip_basic_settings(SETTINGS),
    }

@app.route('/api/v1/config', methods=['POST'])
def update_config():
    """更新配置 (通用接口)"""
    data = request.get_json()
    if not data:
        return {'success': False, 'message': 'No JSON data'}, 400

    updated = []

    # 更新 strength_limit
    if 'strength_limit' in data:
        for channel, value in data['strength_limit'].items():
            channel_key = f'channel_{channel.lower()}'
            if channel_key in SETTINGS['dglab3']:
                value = max(0, min(200, int(value)))
                SETTINGS['dglab3'][channel_key]['strength_limit'] = value
                SETTINGS_BASIC['dglab3'][channel_key]['strength_limit'] = value
                updated.append(f'{channel}_strength_limit={value}')

    # 更新 wave_index
    if 'wave_index' in data:
        idx = int(data['wave_index'])
        if 0 <= idx < len(srv.waveData):
            srv.DEFAULT_WAVE = srv.waveData[idx]
            updated.append(f'wave_index={idx}')

    # 更新自定义波形
    if 'custom_wave' in data:
        srv.DEFAULT_WAVE = data['custom_wave']
        updated.append('custom_wave=set')

    return {
        'success': True,
        'updated': updated,
        'message': f'Updated: {", ".join(updated)}' if updated else 'No changes'
    }

@app.route('/api/v1/config/strength/<channel>/<int:value>', methods=['PUT', 'POST'])
def update_strength_limit(channel, value):
    """动态更新通道软上限

    Args:
        channel: A, B, 或 AB (同时更新两个通道)
        value: 0-200
    """
    channel = channel.upper()
    value = max(0, min(200, value))

    channels = ['A', 'B'] if channel == 'AB' else [channel]
    updated = []

    for chan in channels:
        channel_key = f'channel_{chan.lower()}'
        if channel_key in SETTINGS['dglab3']:
            SETTINGS['dglab3'][channel_key]['strength_limit'] = value
            SETTINGS_BASIC['dglab3'][channel_key]['strength_limit'] = value
            updated.append(chan)
            logger.info(f'[Config] Channel {chan} strength_limit updated to {value}')

    if not updated:
        return {'success': False, 'message': f'Invalid channel: {channel}'}, 400

    return {
        'success': True,
        'channels': updated,
        'strength_limit': value
    }

@app.route('/api/v1/config/wave', methods=['GET'])
def get_wave_config():
    """获取波形配置"""
    return {
        'presets': srv.waveData,
        'current': srv.DEFAULT_WAVE,
        'current_index': srv.waveData.index(srv.DEFAULT_WAVE) if srv.DEFAULT_WAVE in srv.waveData else -1
    }

@app.route('/api/v1/config/wave/<int:index>', methods=['PUT', 'POST'])
def set_wave_preset(index):
    """设置波形预设

    Args:
        index: 波形预设索引 (0-2)
    """
    if 0 <= index < len(srv.waveData):
        srv.DEFAULT_WAVE = srv.waveData[index]
        logger.info(f'[Config] Wave preset set to index {index}')
        return {
            'success': True,
            'index': index,
            'wave': srv.DEFAULT_WAVE
        }
    return {'success': False, 'message': f'Invalid index: {index}, max: {len(srv.waveData)-1}'}, 400

@app.route('/api/v1/config/wave/custom', methods=['PUT', 'POST'])
def set_custom_wave():
    """设置自定义波形"""
    data = request.get_json()
    if not data or 'wave' not in data:
        return {'success': False, 'message': 'Missing wave data'}, 400

    srv.DEFAULT_WAVE = data['wave']
    logger.info(f'[Config] Custom wave set: {data["wave"][:50]}...')
    return {
        'success': True,
        'wave': srv.DEFAULT_WAVE
    }

async def send_osc_status():
    """定期发送设备状态到 VRChat"""
    global osc_client, ble_connector

    osc_config = SETTINGS.get('osc', {})
    if not osc_config.get('output_enabled', True):
        return

    prefix = osc_config.get('output_param_prefix', '/avatar/parameters/ShockingVRChat')
    last_connected = None

    while True:
        await asyncio.sleep(0.5)  # 每 0.5 秒检查一次

        if not osc_client:
            continue

        try:
            connected = ble_connector.connected if ble_connector else False

            # 只在状态变化时发送，或者每 5 秒发送一次
            if connected != last_connected:
                osc_client.send_message(f"{prefix}/Connected", connected)
                logger.info(f"OSC 发送设备状态: Connected = {connected}")
                last_connected = connected
        except Exception as e:
            logger.debug(f"OSC 发送状态失败: {e}")


async def async_main():
    global ble_connector, osc_client

    # 初始化 OSC 输出客户端
    osc_config = SETTINGS.get('osc', {})
    if osc_config.get('output_enabled', True):
        osc_client = SimpleUDPClient(
            osc_config.get('output_host', '127.0.0.1'),
            osc_config.get('output_port', 9000)
        )
        logger.success(f"OSC 输出已启用: {osc_config.get('output_host')}:{osc_config.get('output_port')}")
        # 启动状态发送任务
        asyncio.create_task(send_osc_status())

    # 初始化 BLE 连接
    ble_config = SETTINGS.get('ble', {})
    ble_connector = YCYBLEConnector(
        device_address=ble_config.get('device_address'),
        strength_limit=ble_config.get('strength_limit', 200)
    )

    # 连接 BLE 设备
    scan_timeout = ble_config.get('scan_timeout', 10.0)
    if not await ble_connector.connect(timeout=scan_timeout):
        logger.error("BLE 设备连接失败，请确保设备已开启并在范围内")
        logger.error("程序将继续运行，等待设备连接...")

    # 启动后台任务
    for handler in handlers:
        handler.start_background_jobs()

    # 启动 API 时间管理器
    asyncio.create_task(channel_manager.clear_check_loop())
    logger.success("API 时间管理器已启动")

    # 启动 OSC 服务器
    try:
        server = AsyncIOOSCUDPServer((SETTINGS["osc"]["listen_host"], SETTINGS["osc"]["listen_port"]), dispatcher, asyncio.get_event_loop())
        logger.success(f'OSC Listening: {SETTINGS["osc"]["listen_host"]}:{SETTINGS["osc"]["listen_port"]}')
        transport, protocol = await server.create_serve_endpoint()
    except Exception as e:
        logger.error(traceback.format_exc())
        logger.error("OSC UDP Recevier listen failed.")
        logger.error("OSC监听失败，可能存在端口冲突")
        return

    # 保持运行
    try:
        await asyncio.Future()  # run forever
    except asyncio.CancelledError:
        pass
    finally:
        transport.close()
        if ble_connector:
            await ble_connector.disconnect()

def async_main_wrapper():
    """Not async Wrapper around async_main to run it as target function of Thread"""
    asyncio.run(async_main())

def config_save():
    with open(CONFIG_FILENAME, 'w', encoding='utf-8') as fw:
        yaml.safe_dump(SETTINGS, fw, allow_unicode=True)
    with open(CONFIG_FILENAME_BASIC, 'w', encoding='utf-8') as fw:
        yaml.safe_dump(SETTINGS_BASIC, fw, allow_unicode=True)

class ConfigFileInited(Exception):
    pass

def config_init():
    logger.info(f'Init settings..., Config filename: {CONFIG_FILENAME_BASIC} {CONFIG_FILENAME}, Config version: {CONFIG_FILE_VERSION}.')
    global SETTINGS, SETTINGS_BASIC, SERVER_IP
    if not (os.path.exists(CONFIG_FILENAME) and os.path.exists(CONFIG_FILENAME_BASIC)):
        config_save()
        raise ConfigFileInited()

    with open(CONFIG_FILENAME, 'r', encoding='utf-8') as fr:
        SETTINGS = yaml.safe_load(fr)
    with open(CONFIG_FILENAME_BASIC, 'r', encoding='utf-8') as fr:
        SETTINGS_BASIC = yaml.safe_load(fr)

    if SETTINGS.get('version', None) != CONFIG_FILE_VERSION or SETTINGS_BASIC.get('version', None) != CONFIG_FILE_VERSION:
        logger.error(f"Configuration file version mismatch! Please delete the {CONFIG_FILENAME_BASIC} and {CONFIG_FILENAME} files and run the program again to generate the latest version of the configuration files.")
        raise Exception(f'配置文件版本不匹配！请删除 {CONFIG_FILENAME_BASIC} {CONFIG_FILENAME} 文件后再次运行程序，以生成最新版本的配置文件。')

    SERVER_IP = SETTINGS.get('SERVER_IP') or get_current_ip()

    for chann in ['channel_a', 'channel_b']:
        SETTINGS['dglab3'][chann]['avatar_params'] = SETTINGS_BASIC['dglab3'][chann].get('avatar_params', [])
        SETTINGS['dglab3'][chann]['mode'] = SETTINGS_BASIC['dglab3'][chann].get('mode', 'distance')
        # 确保 strength_limit 有默认值
        raw_limit = SETTINGS_BASIC['dglab3'][chann].get('strength_limit')
        SETTINGS['dglab3'][chann]['strength_limit'] = raw_limit if raw_limit is not None else 200
        logger.info(f"[Config] {chann}: strength_limit from file = {raw_limit}, using = {SETTINGS['dglab3'][chann]['strength_limit']}")

    logger.remove()
    logger.add(sys.stderr, level=SETTINGS['log_level'])
    logger.success("Configuration initialized. BLE mode enabled - will scan for YCY device.")
    logger.success("配置文件初始化完成，BLE 模式已启用 - 将扫描役次元设备。")

def main():
    global dispatcher, handlers
    dispatcher = Dispatcher()
    handlers = []

    for chann in ['A', 'B']:
        config_chann_name = f'channel_{chann.lower()}'
        chann_mode = SETTINGS['dglab3'][config_chann_name]['mode']
        chann_strength_limit = SETTINGS['dglab3'][config_chann_name].get('strength_limit', 200)
        shock_handler = ShockHandler(SETTINGS=SETTINGS, channel_name=chann)
        handlers.append(shock_handler)
        logger.success(f"Channel {chann} Mode: {chann_mode}, Strength Limit: {chann_strength_limit}")
        for param in SETTINGS['dglab3'][config_chann_name]['avatar_params']:
            logger.success(f"  Listening: {param}")
            dispatcher.map(param, shock_handler.osc_handler)
    
    if 'machine' in SETTINGS and 'tuya' in SETTINGS['machine']:
        TuyaConn = TuYaConnection(
            access_id=SETTINGS['machine']['tuya']['access_id'],
            access_key=SETTINGS['machine']['tuya']['access_key'],
            device_ids=SETTINGS['machine']['tuya']['device_ids'],
        )
        machine_tuya_handler = TuyaHandler(SETTINGS=SETTINGS, DEV_CONN=TuyaConn)
        handlers.append(machine_tuya_handler)
        for param in SETTINGS['machine']['tuya']['avatar_params']:
            logger.success(f"Machine Listening：{param}")
            dispatcher.map(param, machine_tuya_handler.osc_handler)


    th = Thread(target=async_main_wrapper, daemon=True)
    th.start()

    if SETTINGS['general']['auto_open_qr_web_page']:
        import webbrowser
        webbrowser.open_new_tab(f"http://127.0.0.1:{SETTINGS['web_server']['listen_port']}")
    else:
        info_ip = SETTINGS['web_server']['listen_host']
        if info_ip == '0.0.0.0':
            info_ip = get_current_ip()
        logger.success(f"请打开浏览器访问 http://{info_ip}:{SETTINGS['web_server']['listen_port']}")
    app.run(SETTINGS['web_server']['listen_host'], SETTINGS['web_server']['listen_port'], debug=False)

if __name__ == "__main__":
    try:
        config_init()
        main()
    except ConfigFileInited:
        logger.success('The configuration file initialization is complete. Please modify it as needed and restart the program.')
        logger.success('配置文件初始化完成，请按需修改后重启程序。')
    except Exception as e:
        logger.error(traceback.format_exc())
        logger.error("Unexpected Error.")
    logger.info('Exiting in 1 seconds ... Press Ctrl-C to exit immediately')
    logger.info('退出等待1秒 ... 按Ctrl-C立即退出')
    time.sleep(1)