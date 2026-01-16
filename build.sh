#!/bin/bash
echo "========================================"
echo "  Shocking VRChat YCY - 打包工具"
echo "========================================"
echo

# 安装依赖
echo "[1/3] 安装依赖..."
pip install -r requirements.txt -q
pip install pyinstaller -q

# 安装 pydglab_ws_ycy
if [ -f "pydglab_ws_ycy-1.2.0-py3-none-any.whl" ]; then
    echo "[2/3] 安装 pydglab_ws_ycy..."
    pip install pydglab_ws_ycy-1.2.0-py3-none-any.whl -q
else
    echo "[警告] 未找到 pydglab_ws_ycy-1.2.0-py3-none-any.whl"
fi

# 打包
echo "[3/3] 开始打包..."
pyinstaller build.spec --noconfirm

echo
if [ -f "dist/ShockingVRChat-YCY" ] || [ -f "dist/ShockingVRChat-YCY.exe" ]; then
    echo "========================================"
    echo "  打包成功！"
    echo "  输出目录: dist/"
    echo "========================================"

    # 复制配置文件
    cp settings-v0.2.yaml dist/ 2>/dev/null
    cp settings-advanced-v0.2.yaml dist/ 2>/dev/null
else
    echo "[错误] 打包失败，请检查错误信息"
fi
