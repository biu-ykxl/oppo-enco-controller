@echo off
rem OPPO Enco Controller 一键打包脚本
cd /d "%~dp0"

echo [1/3] 安装依赖...
python -m pip install -r requirements.txt -q
python -m pip install --upgrade pyinstaller -q

echo [2/3] 打包 EXE...
python -m PyInstaller OppoEncoCC.spec --noconfirm --clean

echo [3/3] 复制产物...
if exist dist\OppoEncoController.exe copy /y dist\OppoEncoController.exe .\

echo.
echo 完成：dist\OppoEncoController.exe（单文件，无需 Python）
pause
