@echo off
rem ============================================
rem   Patho-COT 病理智能诊断系统 - 一键安装依赖
rem   需要联网（首次安装约下载 3~4GB，耗时较长）
rem ============================================
chcp 936 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Patho-COT 一键安装依赖

echo ============================================
echo   Patho-COT 病理智能诊断系统 - 安装运行环境
echo ============================================
echo.

rem ---------- 1) 找一个 Python 3.10+ 解释器 ----------
set "PY="
for %%P in (
    "%LOCALAPPDATA%\Python\pythoncore-3.12-64\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    "C:\Python312\python.exe"
    "C:\Python311\python.exe"
    "C:\Python310\python.exe"
) do (
    if not defined PY if exist %%~P set "PY=%%~P"
)

if not defined PY (
    for %%V in (3.12 3.11 3.10) do (
        if not defined PY (
            for /f "delims=" %%E in ('py -%%V -c "import sys;print(sys.executable)" 2^>nul') do set "PY=%%E"
        )
    )
)
if not defined PY (
    for /f "delims=" %%E in ('python -c "import sys;print(sys.executable)" 2^>nul') do set "PY=%%E"
)

if not defined PY (
    echo [错误] 本机没有找到 Python 3.10 及以上版本。
    echo.
    echo   请先安装 Python 3.12（64 位），下载地址：
    echo   https://www.python.org/downloads/release/python-31210/
    echo   安装时务必勾选 "Add python.exe to PATH"。
    echo   装好后重新双击本文件即可。
    echo.
    pause
    exit /b 1
)

echo [1/5] 使用 Python 解释器:
echo        "%PY%"
"%PY%" -c "import sys; assert sys.version_info[:2]>=(3,10), 'need 3.10+'; print('   版本:', sys.version)"
if errorlevel 1 (
    echo [错误] 该 Python 版本低于 3.10，请安装 Python 3.12。
    pause
    exit /b 1
)

rem ---------- 2) 创建虚拟环境 ----------
echo.
echo [2/5] 创建虚拟环境 .venv （若已存在则复用）...
if not exist ".venv\Scripts\python.exe" (
    "%PY%" -m venv ".venv"
)
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo [错误] 虚拟环境创建失败，请确认 Python 安装完整（含 venv 模块）。
    pause
    exit /b 1
)
set "VPY=%~dp0.venv\Scripts\python.exe"

rem ---------- 3) 升级 pip ----------
echo.
echo [3/5] 升级 pip ...
"%VPY%" -m pip install --upgrade pip

rem ---------- 4) 安装依赖 ----------
echo.
echo [4/5] 安装依赖包（约 3~4GB，视网速可能要十几分钟到半小时）...
echo       torch / torchvision 走 PyTorch 官方 CUDA 12.8 索引，
echo       其余包走 PyPI；请保持联网，中途不要关闭窗口。
echo.
"%VPY%" -m pip install -r "%~dp0patho_cot_web\requirements.txt" --index-url https://download.pytorch.org/whl/cu128 --extra-index-url https://pypi.org/simple
if errorlevel 1 (
    echo.
    echo [提示] 依赖安装过程中出现错误。常见原因：网络中断 / 下载超时。
    echo        请确认能访问 download.pytorch.org 与 pypi.org，然后重新双击本文件重试。
    pause
    exit /b 1
)

rem ---------- 5) 安装随包附带的 segment-anything ----------
echo.
echo [5/5] 安装随包附带的 segment-anything（SAM 细胞分割）...
"%VPY%" -m pip install "%~dp0segment-anything-main"
if errorlevel 1 (
    echo [错误] segment-anything 安装失败。请检查 segment-anything-main 文件夹是否完整。
    pause
    exit /b 1
)

rem ---------- 自检 ----------
echo.
echo ---------- 环境自检 ----------
"%VPY%" -c "import torch, transformers, diffusers, ultralytics, tiatoolbox, segment_anything; print('依赖导入 OK'); print('torch', torch.__version__); print('CUDA 可用:', torch.cuda.is_available())"

echo.
echo ============================================
echo   安装完成！
echo   以后每次使用，双击「启动系统.bat」即可。
echo ============================================
pause
