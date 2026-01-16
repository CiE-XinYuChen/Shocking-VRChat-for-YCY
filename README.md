# Shocking VRChat for YCY (BLE 直连版)

[English version](README_en.md)

一个小工具，通过接受 VRChat Avatar 的 OSC 消息，**使用蓝牙 BLE 直接连接役次元 (YCY) 设备**，达到游戏中 Avatar 被别人/自己触摸，就会被电的效果。

> [!NOTE]
> **本版本为 BLE 直连版**，无需手机 APP 中转，直接通过电脑蓝牙连接役次元设备。
>
> 原版 WebSocket 版本请访问：[VRChatNext/Shocking-VRChat](https://github.com/VRChatNext/Shocking-VRChat)

我们的 VRChat 群组： [ShockingVRC https://vrc.group/SHOCK.2911](https://vrc.group/SHOCK.2911)

> [!CAUTION]
> 您必须阅读并同意 [安全须知](doc/dglab/安全须知.md) ([Safety Precautions](doc/dglab/SafetyPrecautions.md) in English) 后才可以使用本工具！

## 与原版的区别

| 特性 | 原版 (WebSocket) | 本版本 (BLE 直连) |
|------|------------------|-------------------|
| 连接方式 | 手机 APP 扫码 → WebSocket | 电脑蓝牙直连设备 |
| 需要手机 | 是 | 否 |
| 支持设备 | 郊狼 DG-LAB 3.0 | 役次元 (YCY) |
| 波形控制 | 自定义波形队列 | 强度控制 + 时间队列 |
| 延迟 | 较高 (网络+APP) | 较低 (BLE 直连) |

## 使用方式

1. 确保电脑有蓝牙功能，并已开启
2. 开启役次元设备，确保设备处于可被发现状态
3. 首次运行程序，将会在当前目录生成设置文件并退出
4. 在配置文件 `settings-v*.*.yaml` 中填入 `avatar_params` 与工作模式（shock/distance/touch）
5. （可选）按需修改进阶配置文件 `settings-advanced-v*.*.yaml`
6. 重新运行程序，程序将自动扫描并连接役次元设备
7. 看到 `BLE 连接成功!` 后即可开始使用
8. 访问 `http://127.0.0.1:8800/status` 查看实时状态

## BLE 连接说明

- 程序启动时会自动扫描附近的役次元设备
- 默认扫描超时时间为 10 秒
- 如需指定设备地址，可在进阶配置文件中设置 `ble.device_address`
- 连接成功后，设备地址会显示在日志中

## 波形队列与时间管理 (BLE 模式)

由于 BLE 直连模式无法像 WebSocket 版本那样发送自定义波形队列，本版本采用**强度控制 + 时间队列**的方式模拟波形效果：

### 工作原理

1. **强度映射**：将原版波形数据中的强度值 (0-100) 映射到设备强度 (0-200)
2. **时间队列**：每个波形包代表 100ms，多个包的时间会叠加
3. **自动清除**：队列时间结束后，强度自动归零

### 示例

```
API 调用: /api/v1/sendwave/A/10/0A0A0A0A64646464
- 通道: A
- 重复: 10 次 = 1000ms
- 波形: 0A0A0A0A64646464 (强度 0x64 = 100%)
- 结果: 设置 A 通道强度为 100 (受 strength_limit 限制)，1 秒后自动归零
```

### 时间叠加

连续调用 API 时，时间会叠加而非覆盖：
- 第一次调用 `sendwave/A/10/...` → A 通道 1000ms 后清除
- 立即第二次调用 `sendwave/A/5/...` → A 通道再延长 500ms，共 1500ms 后清除

## 工作模式解释

### distance 距离模式

- 根据与触发区域中心的距离控制强度
- 越接近中心，强度越强
- 距离模式下 trigger_range 的含义
    - 当接收到的 OSC 数据大于 bottom 时，开始线性变化强度，上界为 top
    - 当数据达到或超过 top 参数后，以最大强度输出
    - 建议 bottom 设置为 0 或较小数字
    - 建议 top 设置为 1.0 以获得最大动态范围

### shock 电击模式

- 触发后电击固定时长（默认：2秒）
- 如果一直被触碰，会电击到触摸离开后的固定时长
- 电击模式下 trigger_range 的含义
    - 当接收到的 OSC 数据大于 bottom 时，触发电击
    - top 参数在 shock 模式被忽略

### touch 触摸模式

- 根据触摸速度/加速度控制强度
- 支持多种导数模式 (距离、速度、加速度、加加速度)


## 基础配置文件参考

配置文件格式 `yaml`， 当前配置文件版本: `v0.2` 。

```yaml
dglab3:
  channel_a:
    avatar_params:  
    # 此处填写 OSC 监听参数组，可以使用通配符 * 匹配任意字符串，注意保留正确缩进与前缀的 “- ” 
    # 可参考 https://python-osc.readthedocs.io/en/latest/dispatcher.html#mapping 
    - /avatar/parameters/pcs/contact/enterPass
    - /avatar/parameters/Shock/wildcard/*
    mode: distance # 工作模式，此处为距离模式
    strength_limit: 100 # 强度限制，程序将取该强度与主机设置的强度中最大的一个
  channel_b:
    avatar_params:
    - /avatar/parameters/lms-penis-proximityA*
    - /avatar/parameters/ShockB2/some/param
    mode: shock # 工作模式，此处为电击模式
    strength_limit: 100
version: v0.2
```

## 模型参数配置

- 程序内部流转处理的参数为 0 ~ 1 之间的 float
- 支持输入的参数类型为 float、int、bool
    - float，int ：小于 0 会被视为 0，大于 1 会被视为 1
    - bool ：True 为 1，False 为 0
- 其他参数类型会报错

## 常见参数

> 本部分请协助补充描述与解释。

- float
  - /avatar/parameters/pcs/contact/enterPass
    - 最常用，位于pcs触发入口处，可自动切换跟随被触发的位置
  - /avatar/parameters/pcs/contact/proximityA
  - /avatar/parameters/pcs/contact/proximityB
  - /avatar/parameters/pcs/contact/slide
    - 不推荐使用，pcs开启后前后移动会触发很多次
  - /avatar/parameters/pcs/smash-intensity
  - /avatar/parameters/pcs/sps/pussy
    - 如果需要仅通过指定位置触发，可尝试 pcs/sps 下的参数，不会跟随auto mode位置变化
  - /avatar/parameters/pcs/sps/ass
  - /avatar/parameters/pcs/sps/boobs
  - /avatar/parameters/pcs/sps/mouth
  - /avatar/parameters/pcs/sps/penis*
  - /avatar/parameters/lms-penis-proximityA*
    - 通过 LMS 1.2 触发可以使用的参数
  - /avatar/parameters/lms/contact/proximity
    - 通过 LMS 1.3 触发可以使用的参数
- bool
  - /avatar/parameters/pcs/smash-intense
  - /avatar/parameters/pcs/contact/in
  - /avatar/parameters/pcs/contact/out
  - /avatar/parameters/pcs/contact/hit
  - /avatar/parameters/lms-stroke-in
  - /avatar/parameters/lms-stroke-out*
  - /avatar/parameters/lms-stroke-smash

## 进阶配置文件参考

```yaml
ble: # BLE 连接配置 (本版本新增)
  device_address: null  # 设备蓝牙地址，留空则自动扫描
  scan_timeout: 10.0    # 扫描超时时间（秒）
  strength_limit: 200   # 全局强度上限 (0-200)

dglab3:
  channel_a: # 通道 A 配置
    mode_config:   # 工作模式配置
      distance:
        freq_ms: 10  # 强度更新频率（毫秒）
      shock:
        duration: 2  # 触发后的电击时长
        wave: '["0A0A0A0A64646464"]'  # 电击波形 (BLE 模式下仅解析强度)
      touch:
        freq_ms: 10
        n_derivative: 1  # 0=距离, 1=速度, 2=加速度, 3=加加速度
        derivative_params:
          - {top: 1, bottom: 0}
          - {top: 5, bottom: 0}
          - {top: 50, bottom: 0}
          - {top: 500, bottom: 0}
      trigger_range:
        bottom: 0.0  # OSC 回报参数触发下界
        top: 0.8     # OSC 回报参数触发上界
  channel_b: # 通道 B 配置，参数设置与 A 通道相同
    mode_config:
      distance:
        freq_ms: 10
      shock:
        duration: 2
        wave: '["0A0A0A0A64646464"]'
      touch:
        freq_ms: 10
        n_derivative: 1
        derivative_params:
          - {top: 1, bottom: 0}
          - {top: 5, bottom: 0}
          - {top: 50, bottom: 0}
          - {top: 500, bottom: 0}
      trigger_range:
        bottom: 0.1
        top: 0.8

general: # 通用配置
  auto_open_qr_web_page: false  # BLE 模式不需要二维码
  local_ip_detect:
    host: 223.5.5.5
    port: 80

log_level: INFO  # 日志等级，诊断问题时可以改为 DEBUG

osc: # OSC 服务配置
  listen_host: 127.0.0.1
  listen_port: 9001
  # OSC 输出配置 (向 VRChat 发送设备状态)
  output_host: 127.0.0.1
  output_port: 9000
  output_param_prefix: /avatar/parameters/ShockingVRChat
  output_enabled: true

web_server: # Web 服务器配置
  listen_host: 127.0.0.1
  listen_port: 8800

version: v0.2
```

## FAQ

### 是否有逃生通道

- 有，可以按一下设备的物理按钮，此时 A B 通道强度会被设置为 0。
- 也可以直接关闭程序或关闭设备电源。
- BLE 直连模式下，关闭程序后设备会立即停止输出。

### 应该如何设置上限

- **BLE 版本使用 `strength_limit` 配置**：在 `settings-v*.*.yaml` 基础配置文件中，每个通道可以独立设置 `strength_limit` (0-200)。
- 默认值为 100，如需更高强度请调整此参数。
- 也可在进阶配置文件中设置 `ble.strength_limit` 作为全局上限。

### 想用一个参数同时触发两个通道

- 请将需要使用的参数，例如 `/avatar/parameters/pcs/contact/enterPass` 同时复制进基础配置文件 `settings-v*.*.yaml` 内 `channel_a` 和 `channel_b` 的 `avatar_params` 列表内，请注意缩进与行首的 `-` 。

### OSC 端口冲突了怎么办

报错中显示 `OSC监听失败` 或包含 `create_datagram_endpoint` 的 `WinError 10048` 为该问题。该问题一般是和面捕软件冲突导致。

```
Exception in thread Thread-1 (async_main_wrapper):
Traceback (most recent call last):
  ...
  File "shocking_vrchat.py", line 143, in async_main_wrapper
  ...
  File "shocking_vrchat.py", line 135, in async_main
  File "asyncio\base_events.py", line 1387, in create_datagram_endpoint
  File "asyncio\base_events.py", line 1371, in create_datagram_endpoint
OSError: [WinError 10048] 通常每个套接字地址(协议/网络地址/端口)只允许使用一次。
```
1. 请前往 [osc-repeater](https://github.com/CyCoreSystems/osc-repeater) 从 Release 下载 osc-repeater
2. 解压后在 `osc-repeater_x.x.x_windows_amd64.exe` 同目录创建配置文件，名为 `config.yaml`，文件内容：
```
listenPorts:
  - 9001
targets:
  - "127.0.0.1:9011"
  - "127.0.0.1:9021"
```
3. （可选）如果你的 VRChat 存在特殊OSC设置，请按照需要修改 `9001` 为实际端口号
4. 在面捕软件中修改 OSC Receiver 端口号为 `9011`，保存后退出面捕软件
5. 修改 ShockingVRChat 的 `settings-advanced-v*.*.yaml` 进阶配置，设置 `osc` 的 `listen_port` 为 `9021`
6. **请确认已经退出**面捕程序和ShockingVRChat（本软件）
7. 依次双击运行 `osc-repeater`、面捕程序、ShockingVRChat

*以后使用时只执行步骤 7 即可，如果只用面捕也需要启动 `osc-repeater`

### 控制台内有输出，但是没有强度或强度显著变小

- 确认贴片正常连接，确认电线正常连接
- 检查 `strength_limit` 配置是否设置过低
- 访问 `http://127.0.0.1:8800/status` 查看设备电极连接状态

### 程序看起来收不到 OSC 数据

1. **如果你有面捕**，请检查 Steam 中 VRChat 的启动命令行参数，是否有类似 `--osc=9000:127.0.0.1:9001` 的配置，如有，请修改进阶配置文件，`osc` `listen_port` 的值为最后一个冒号后的值，如 9001。
2. Action Menu 中选择 Options > OSC > Reset Config 重置 OSC 配置
3. 如果之前是正常使用的，但忽然收不到，重启电脑可以解决问题，似乎是 VRChat 的 Bug。
4. 目前**已知会占用 UDP 9000 端口导致 VRChat OSC组件启动失败的程序**，请退出以下程序并重置OSC。
    - 酷狗音乐

### 为什么强度一直是最大可用值

- **BLE 版本**：强度由基础配置文件内的 `strength_limit` 控制，程序会根据触发距离在 0 到 `strength_limit` 之间线性变化。
- 实际被触发的强度是由触发实体（例如他人的手）距离触发区域（例如 enterPass）中心点的距离决定，线性提升。
- 如需修改判定上下界请用 `trigger_range` 配置。

### BLE 扫描找不到设备

1. 确认设备已开机并处于可被发现状态（通常设备指示灯会闪烁）
2. 确认电脑蓝牙已开启
3. 尝试增加扫描超时时间：在进阶配置文件中设置 `ble.scan_timeout` 为更大的值（默认 10 秒）
4. 如果知道设备地址，可在进阶配置文件中设置 `ble.device_address` 直接连接
5. 关闭其他可能占用蓝牙的程序后重试

### BLE 连接不稳定/断开重连

1. 确保设备与电脑距离较近（建议 3 米以内）
2. 避免蓝牙信号被遮挡（如金属物体）
3. 程序会自动尝试重连，如果频繁断开，检查设备电量

### 程序版本更新后配置文件如何继承？

- 程序版本与配置文件版本分离，如果仅仅是程序版本更新，配置文件无需改动即可继承使用。
- 如果配置文件版本发生更新，原配置不会被覆盖，请观察新配置文件的变更位置，将需要保留的参数填入新配置文件。

### OSC 能收到其他参数但收不到模型的参数

- 如果你的模型是刚刚修改过的，有可能是 VRChat 的 OSC 配置文件没有更新，请尝试在 Action Menu 中选择 Options > OSC > Reset Config 重置 OSC 配置。

## Credits

感谢 [DG-LAB-OPENSOURCE](https://github.com/DG-LAB-OPENSOURCE/DG-LAB-OPENSOURCE) ，赞美 DG-LAB 的开源精神！

感谢 [PyDGLab-WS-for-YCY](https://github.com/CiE-XinYuChen/PyDGLab-WS-for-YCY) 提供的役次元设备 BLE 连接支持！

感谢原版 [VRChatNext/Shocking-VRChat](https://github.com/VRChatNext/Shocking-VRChat) 项目！

感谢以下用户对常见参数部分的协助：ichiAkagi

-----

## 安全须知

**为了您能健康地享受产品带来的乐趣，请在使用前确保已阅读并理解本安全须知的全部内容。**  
**错误使用本产品可能对您或者他人造成伤害，由此产生的责任将由您自行承担。**

感谢您选择DG-LAB系列产品，用户的安全始终是我们的第一要务。  
本产品为情趣用品，请保证在**安全，清醒，自愿**的情况下使用。并将其放置于未成年人接触不到的地方。

本安全须知大约需要**2分钟**阅读。

### **下列人群严禁使用本产品：**

1. **佩戴心脏起搏器，或体内有电子/金属植入物的人群**（可能影响起搏器或植入物的正常功能）
2. **癫痫，哮喘、心脏病、血栓及其他心脑血管疾病患者**（感官刺激可能诱发或加重症状）
3. **皮肤敏感，皮炎及其他皮肤疾病患者**（可能使皮肤疾病症状加重）
4. **有出血倾向性疾病的患者**(电刺激会使局部毛细血管扩张从而可能诱发出血)
5. 未成年人、孕妇、知觉异常及无表达意识能力的人群
6. 肢体运动障碍及其他**无法及时操作产品**的人群（可能在感到不适时无法及时停止输出）
7. 其他正在接受治疗或身体不适的人群。

### **下列部位严禁使用本产品：**

1. 严禁将电极置于胸部；**绝对禁止将两电极分别置于心脏投影区前后、左右**或任何可能使电流流经心脏的位置；
2. 严禁将电极置于**头部、面部，眼部、口腔、颈部**及颈动脉窦附近；
3. 严禁将电极置于**皮肤破损或水肿处，关节扭伤挫伤处，肌肉拉伤处，炎症/感染病灶处，或未完全愈合的伤口**附近。

### **其他注意事项：**

1. **严禁在同一部位连续使用30分钟以上，**长时间使用可能导致局部红肿或知觉减弱等其他损伤。
2. 严禁在输出状态下移动电极，**在移动电极或更换电极时，必须先停止输出，**避免接触面积变化导致刺痛或灼伤。
3. 严禁在驾驶或操作机器等危险情况下使用，**以避免受脉冲影响而失去控制。**
4. 严禁将电极导线插入产品主机导线插孔之外的地方（如电源插座等）。
5. 严禁在具有易燃易爆物质的场合使用。
6. **请勿同时使用多台产品。**
7. 请勿私自拆卸或修理产品主机，可能会引起故障或意料外的输出。
8. 请勿在浴室等潮湿环境使用。
9. 在使用过程中，**请勿使两电极互相接触短路，**可能导致感受减弱，接触部位刺痛或灼伤，或损坏设备。
10. 电极使用时必须与皮肤充分紧密接触，如果电极与皮肤的接触面积过小，可能导致刺痛或灼伤。如果电极与皮肤的接触面积过大，则可能导致电感微弱。
11. 产品内含锂电池，禁止拆解，装机，挤压或投入火中。若产品出现**故障或异常发热**，请勿继续使用。

### **重要使用提示：**

1. 由于不同部位对于电流耐受程度存在差异，且一些材质的电极可能使少部分用户出现过敏现象。**当您在一个部位首次使用本产品时，或使用一款新的电极时，请先试用10分钟**之后等待一段时间，确认使用部位无异常后方可继续使用。
2. 受人体生理特性的影响，身体对于脉冲刺激的感受会逐渐变弱，因此，在使用过程中可能需要逐渐增加强度来保持相对稳定的体感强度。  
这有可能导致**在同一部位过长时间使用本产品后，真实刺激强度已经逐渐超过可承受的范围但是却没有被感觉到，**从而造成损伤。  
虽然本产品的最高输出严格低于安全标准的限制（r.m.s < 50ma，500Ω），但长时间使用仍然有可能造成损伤。因此，请在使用过程中**严格遵守连续使用时长的限制**。在同一部位连续使用**30分钟**后请休息一段时间，让感受灵敏度恢复到正常水平。
3. 连续不断的高频刺激会使使用部位快速适应，建议使用**频率不断变化且间歇休息**的波形，从而获得更好的使用体验。以每小段波形刺激时间1-10秒，休息1-10秒为宜。
