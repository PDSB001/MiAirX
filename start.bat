@echo off
chcp 65001 >nul
title MiAirX - 小米音箱 DLNA/AirPlay 桥接器

echo.
echo ============================================================
echo MiAirX - 小米音箱 DLNA/AirPlay 桥接器
echo ============================================================
echo.

cd /d "%~dp0"

echo [启动服务]
echo   配置文件: conf\config.json
echo   DLNA 端口: 8200
echo   Web 端口: 8300
echo   Web 界面: http://localhost:8300
echo.
echo   按 Ctrl+C 停止服务
echo.
echo ------------------------------------------------------------
echo.

set PYTHONPATH=src
python -m miairx

if errorlevel 1 (
    echo.
    echo [错误] 启动失败，请检查配置文件
    echo.
    pause
)
