@echo off
chcp 65001 >nul
echo ========================================
echo   Shocking VRChat YCY - 打包工具
echo ========================================
echo.

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.8+
    pause
    exit /b 1
)

REM 安装依赖
echo [1/3] 安装依赖...
pip install -r requirements.txt -q
pip install pyinstaller -q

REM 安装 pydglab_ws_ycy
if exist "pydglab_ws_ycy-1.2.0-py3-none-any.whl" (
    echo [2/3] 安装 pydglab_ws_ycy...
    pip install pydglab_ws_ycy-1.2.0-py3-none-any.whl -q
) else (
    echo [警告] 未找到 pydglab_ws_ycy-1.2.0-py3-none-any.whl
)

REM 打包
echo [3/3] 开始打包...
pyinstaller build.spec --noconfirm

echo.
if exist "dist\ShockingVRChat-YCY.exe" (
    echo ========================================
    echo   打包成功！
    echo   输出文件: dist\ShockingVRChat-YCY.exe
    echo ========================================

    REM 复制配置文件模板到 dist
    if not exist "dist\settings-v0.2.yaml" (
        copy "settings-v0.2.yaml" "dist\" >nul 2>&1
    )
    if not exist "dist\settings-advanced-v0.2.yaml" (
        copy "settings-advanced-v0.2.yaml" "dist\" >nul 2>&1
    )
) else (
    echo [错误] 打包失败，请检查错误信息
)

echo.
pause
