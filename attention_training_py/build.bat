@echo off
chcp 65001 >nul
echo ========================================
echo   🔴 Release 模式打包工具
echo ========================================
echo.
echo 打包配置：
echo   - 模式: Release
echo   - 控制台: 隐藏
echo   - 压缩: UPX (如果可用)
echo   - 调试信息: 移除
echo   - 优化: 开启
echo.

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请安装 Python 3.8+
    pause
    exit /b 1
)

REM 检查 PyInstaller
python -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo [安装] PyInstaller 未安装，正在安装...
    pip install pyinstaller
)

REM 检查 UPX
upx --version >nul 2>&1
if errorlevel 1 (
    echo [警告] UPX 未安装，将不进行压缩
    echo        下载地址: https://upx.github.io/
) else (
    echo [信息] UPX 已安装
)

echo.
echo [开始] 打包 Release 版本...
python dynamic_build_fixed.py

if errorlevel 1 (
    echo.
    echo [失败] Release 打包失败
) else (
    echo.
    echo [成功] Release 打包完成！
    echo 程序位置: dist\AttentionTrainingApp\
)

pause