@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    echo 首次运行，正在创建虚拟环境并安装依赖...
    python -m venv .venv
    .venv\Scripts\python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
)
.venv\Scripts\python run.py
