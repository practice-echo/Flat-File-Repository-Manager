@echo off
echo ========================================
echo 私人工具资源仓库管理工具 - 一键打包脚本
echo ========================================
echo.

echo 正在检查图标文件...
if not exist "repo.ico" (
    echo 警告：未找到图标文件 repo.ico
    echo 将使用默认图标打包
    set ICON_PARAM=
) else (
    echo 找到图标文件 repo.ico
    set ICON_PARAM=--icon "repo.ico"
)

echo.
echo 正在打包（使用uv run）...
uv run pyinstaller --onefile --console --name "资源仓库管理工具" --clean ^
%ICON_PARAM% ^
--hidden-import pymysql ^
--hidden-import colorama ^
--hidden-import subprocess ^
--hidden-import mode.database ^
--hidden-import mode.flow ^
--hidden-import mode.point ^
--hidden-import mode.import_folder ^
--hidden-import mode.organizer ^
--hidden-import mode.help ^
--hidden-import mode.backup ^
--hidden-import mode.file_ops ^
--hidden-import mode.move_flow ^
--hidden-import mode.config ^
--exclude-module tkinter ^
--exclude-module matplotlib ^
--exclude-module numpy ^
--exclude-module PIL ^
--exclude-module PyQt5 ^
--exclude-module test ^
--exclude-module unittest ^
--upx-exclude vcruntime140.dll ^
--upx-exclude ucrtbase.dll ^
--upx-exclude python311.dll ^
main.py

echo.
echo ========================================
echo 打包完成！
echo EXE文件位于：dist\资源仓库管理工具.exe
echo ========================================
echo.
pause