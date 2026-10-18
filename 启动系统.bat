@echo off
rem ============================================
rem   Patho-COT 病理智能诊断系统 - 一键启动
rem   启动后浏览器访问 http://127.0.0.1:8001
rem ============================================
chcp 936 >nul
cd /d "%~dp0"
title Patho-COT 病理智能诊断系统

if not exist "%~dp0.venv\Scripts\python.exe" (
    echo.
    echo [错误] 还没有安装运行环境 .venv
    echo 请先双击本文件夹里的「一键安装依赖.bat」，等它跑完再启动。
    echo.
    pause
    exit /b 1
)

rem 让系统从本文件夹自动发现模型权重（无需改 config.yaml）
set "PATHO_COT_MODEL_ROOT=%~dp0"

echo ============================================
echo   Patho-COT 病理智能诊断系统正在启动...
echo ============================================
echo   浏览器地址: http://127.0.0.1:8001
echo   首次分析要加载模型，约需 30~60 秒，请耐心等待。
echo   关闭本窗口 或 按 Ctrl+C 可停止服务。
echo.

rem 等 6 秒后自动打开浏览器首页
start "" /b cmd /c "timeout /t 6 /nobreak >nul & start http://127.0.0.1:8001/"

cd /d "%~dp0patho_cot_web"
"%~dp0.venv\Scripts\python.exe" -m uvicorn app:app --host 0.0.0.0 --port 8001

echo.
echo 服务已停止。
pause
