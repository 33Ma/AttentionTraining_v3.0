@echo off
chcp 65001 >nul
title 动态封装打包 - AttentionTrainingApp
echo ================================================
echo   注意力训练系统 - 动态封装打包工具
echo ================================================
echo   模式 : Release (onedir, 无控制台)
echo   产物 : dist\AttentionTrainingApp\
echo ================================================
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.9+ 并加入 PATH。
    pause
    exit /b 1
)

python -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo [信息] PyInstaller 未安装，将自动安装...
)

echo [开始] 动态收集模块并打包...
python dynamic_build.py --clean %*

if errorlevel 1 (
    echo.
    echo [失败] 打包失败，请查看上方日志。
) else (
    echo.
    echo [成功] 打包完成！
    echo 程序位置: dist\AttentionTrainingApp\AttentionTrainingApp.exe
)

pause
