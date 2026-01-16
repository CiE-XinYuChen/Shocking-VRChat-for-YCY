"""
役次元 BLE 连接器

通过蓝牙直连役次元设备，无需 App 中转。
使用 YCY 预设波形模式，通过强度控制输出。
"""
import asyncio
from typing import Optional, List
from loguru import logger

from pydglab_ws import YCYBLEClient, YCYScanner, Channel, StrengthOperationType
from pydglab_ws.ble import YCYMode

import srv

# YCY 预设模式名称 (1-16)
YCY_MODE_NAMES = [
    "呼吸", "潮汐", "连击", "快速按捏",
    "按捏渐强", "心跳节奏", "压缩", "节奏步伐",
    "信号灯", "弹跳", "挑逗1", "挑逗2",
    "渐强渐弱", "快速渐强", "阶梯渐强", "波浪"
]


class YCYBLEConnector:
    """
    役次元 BLE 连接器

    封装 YCYBLEClient，提供与原 DGConnection 兼容的接口。
    """

    def __init__(self, device_address: str = None, strength_limit: int = 200):
        """
        初始化连接器

        :param device_address: 设备蓝牙地址，留空则自动扫描
        :param strength_limit: 强度上限 (0-200)
        """
        self.device_address = device_address
        self.strength_limit = strength_limit
        self.client: Optional[YCYBLEClient] = None
        self._reconnect_task: Optional[asyncio.Task] = None
        self._auto_reconnect = True
        self._connected_flag = False  # 连接成功标记

    @property
    def connected(self) -> bool:
        """是否已连接 - 使用连接成功标记"""
        return self._connected_flag and self.client is not None

    @property
    def strength_data(self):
        """获取当前强度数据"""
        if self.client:
            return self.client.strength_data
        return None

    async def scan_devices(self, timeout: float = 10.0) -> List:
        """
        扫描役次元设备

        :param timeout: 扫描超时时间
        :return: 设备列表
        """
        logger.info(f"正在扫描役次元设备 (超时: {timeout}s)...")
        devices = await YCYScanner.scan(timeout=timeout)
        for dev in devices:
            logger.info(f"  发现设备: {dev.name} ({dev.address}) RSSI: {dev.rssi}")
        return devices

    async def connect(self, timeout: float = 10.0) -> bool:
        """
        连接设备

        :param timeout: 扫描超时时间 (仅在未指定地址时使用)
        :return: 是否连接成功
        """
        try:
            if self.device_address:
                # 直接连接指定地址
                logger.info(f"正在连接指定设备: {self.device_address}")
                self.client = YCYBLEClient(self.device_address, strength_limit=self.strength_limit)
            else:
                # 扫描并连接第一个设备
                devices = await self.scan_devices(timeout=timeout)
                if not devices:
                    logger.error("未找到役次元设备")
                    return False

                device = devices[0]
                logger.info(f"选择设备: {device.name} ({device.address})")
                self.device_address = device.address
                self.client = YCYBLEClient(device.address, strength_limit=self.strength_limit)

            # 连接
            success = await self.client.connect()
            if success:
                # 设置连接标记
                self._connected_flag = True
                # 更新全局引用
                srv.BLE_CLIENT = self.client

                # 获取电池电量
                try:
                    battery = await self.client.get_battery()
                    logger.success(f"BLE 连接成功! 电池电量: {battery}%")
                except Exception:
                    logger.success("BLE 连接成功!")

                return True
            else:
                self._connected_flag = False
                logger.error("BLE 连接失败")
                return False

        except Exception as e:
            logger.error(f"BLE 连接异常: {e}")
            return False

    async def disconnect(self):
        """断开连接"""
        self._auto_reconnect = False
        self._connected_flag = False
        if self._reconnect_task:
            self._reconnect_task.cancel()

        if self.client:
            await self.client.disconnect()
            srv.BLE_CLIENT = None
            logger.info("BLE 已断开连接")

    async def ensure_connected(self) -> bool:
        """确保已连接，未连接则尝试重连"""
        if self.connected:
            return True
        return await self.connect()

    async def get_battery(self) -> int:
        """获取电池电量"""
        if not self.connected or not self.client:
            return -1
        try:
            return await self.client.get_battery()
        except Exception:
            return -1

    async def get_electrode_status(self, channel: str) -> str:
        """
        获取电极状态

        :return: 'not_connected' | 'connected_active' | 'connected_inactive' | 'unknown'
        """
        if not self.connected or not self.client:
            return 'disconnected'
        try:
            from pydglab_ws.ble import ElectrodeStatus
            ch = Channel.A if channel.upper() == 'A' else Channel.B
            status = await self.client.get_electrode_status(ch)
            if status == ElectrodeStatus.NOT_CONNECTED:
                return 'not_connected'
            elif status == ElectrodeStatus.CONNECTED_ACTIVE:
                return 'connected_active'
            elif status == ElectrodeStatus.CONNECTED_INACTIVE:
                return 'connected_inactive'
            return 'unknown'
        except Exception:
            return 'unknown'

    # ==================== 兼容原 DGConnection 的静态方法 ====================

    @staticmethod
    def _parse_wave_strength(wavestr: str) -> int:
        """
        从波形字符串解析强度值

        波形格式: ["0A0A0A0A32323232"]
        最后4个字节是强度 (00-64 = 0-100)
        """
        try:
            import json
            wave_list = json.loads(wavestr)
            if isinstance(wave_list, list) and len(wave_list) > 0:
                wave = wave_list[0]
                # 取最后2个十六进制字符 (强度值)
                strength_hex = wave[-2:]
                strength = int(strength_hex, 16)
                return strength  # 0-100
        except Exception:
            pass
        return 0

    @staticmethod
    async def broadcast_wave(channel: str, wavestr: str, strength_limit: int = 200):
        """
        发送波形 (兼容原接口)

        改为：解析波形强度，直接设置 YCY 设备强度
        使用预设模式，不发送自定义波形

        :param channel: 通道 'A' 或 'B'
        :param wavestr: JSON 格式的波形数组字符串
        :param strength_limit: 强度软上限 (0-200)，默认200
        """
        client = srv.BLE_CLIENT
        if not client or not client.connected:
            logger.warning("BLE 未连接，无法发送")
            return

        try:
            ch = Channel.A if channel.upper() == 'A' else Channel.B

            # 从波形解析强度 (0-100)
            strength_percent = YCYBLEConnector._parse_wave_strength(wavestr)

            # 转换为 YCY 强度，应用软上限
            # strength_percent (0-100) * strength_limit / 100
            ycy_strength = int(strength_percent * strength_limit / 100)
            ycy_strength = max(0, min(strength_limit, ycy_strength))

            # 设置强度
            await client.set_strength(ch, StrengthOperationType.SET_TO, ycy_strength)
            # 使用 info 级别日志方便调试
            if ycy_strength > 0:
                logger.info(f"Channel {channel}: 强度 {strength_percent}% -> {ycy_strength}/{strength_limit}")
        except Exception as e:
            logger.error(f"设置强度失败: {e}")

    @staticmethod
    async def broadcast_clear_wave(channel: str):
        """
        清除波形队列 (兼容原接口)

        :param channel: 通道 'A' 或 'B'
        """
        client = srv.BLE_CLIENT
        if not client or not client.connected:
            return

        try:
            ch = Channel.A if channel.upper() == 'A' else Channel.B
            await client.clear_pulses(ch)
            logger.debug(f"Channel {channel}: 波形已清除")
        except Exception as e:
            logger.error(f"清除波形失败: {e}")

    @staticmethod
    async def broadcast_strength(channel: str, strength: int):
        """
        设置强度 (兼容原接口)

        :param channel: 通道 'A' 或 'B'
        :param strength: 强度值 (0-200)
        """
        client = srv.BLE_CLIENT
        if not client or not client.connected:
            logger.warning("BLE 未连接，无法设置强度")
            return

        try:
            ch = Channel.A if channel.upper() == 'A' else Channel.B
            await client.set_strength(ch, StrengthOperationType.SET_TO, strength)
            logger.debug(f"Channel {channel}: 强度设置为 {strength}")
        except Exception as e:
            logger.error(f"设置强度失败: {e}")

    @staticmethod
    async def broadcast_strength_0_to_1(channel: str, value: float):
        """
        设置强度 (0.0-1.0 范围, 兼容原接口)

        :param channel: 通道 'A' 或 'B'
        :param value: 强度值 (0.0-1.0)
        """
        client = srv.BLE_CLIENT
        if not client or not client.connected:
            logger.warning("BLE 未连接，无法设置强度")
            return

        try:
            ch = Channel.A if channel.upper() == 'A' else Channel.B
            # 转换为 0-200 范围
            strength = int(value * 200)
            strength = max(0, min(200, strength))
            await client.set_strength(ch, StrengthOperationType.SET_TO, strength)
            logger.debug(f"Channel {channel}: 强度设置为 {value:.2f} ({strength}/200)")
        except Exception as e:
            logger.error(f"设置强度失败: {e}")

    @staticmethod
    async def set_mode(channel: str, mode: int):
        """
        设置预设模式

        :param channel: 通道 'A' 或 'B'
        :param mode: 模式 (1-16)
        """
        client = srv.BLE_CLIENT
        if not client or not client.connected:
            return

        try:
            ch = Channel.A if channel.upper() == 'A' else Channel.B
            ycy_mode = YCYMode(mode) if 1 <= mode <= 16 else YCYMode.PRESET_1
            await client.set_mode(ch, ycy_mode)
            logger.info(f"Channel {channel}: 模式设置为 {ycy_mode.name}")
        except Exception as e:
            logger.error(f"设置模式失败: {e}")

    @staticmethod
    async def stop_all():
        """停止所有通道"""
        client = srv.BLE_CLIENT
        if not client or not client.connected:
            return

        try:
            await client.set_strength(Channel.A, StrengthOperationType.SET_TO, 0)
            await client.set_strength(Channel.B, StrengthOperationType.SET_TO, 0)
            logger.info("所有通道已停止")
        except Exception as e:
            logger.error(f"停止失败: {e}")
