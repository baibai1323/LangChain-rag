@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [错误] 未找到 .venv，请先执行：
  echo   python -m venv .venv
  echo   .venv\Scripts\python.exe -m pip install -r backend\requirements.txt
  pause
  exit /b 1
)

if not exist ".env" (
  echo [提示] 未找到 .env。请在本目录手动新建 .env，写入一行：
  echo        DASHSCOPE_API_KEY=你的百炼APIKey
  echo        或改用同名系统环境变量。否则问答与入库会失败。
)

if not exist "frontend\dist\index.html" (
  echo [提示] 未找到前端构建产物，正在尝试构建...
  pushd frontend
  call npm run build
  popd
)

echo 启动服务：http://127.0.0.1:8000
start "" http://127.0.0.1:8000
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --app-dir backend

pause
