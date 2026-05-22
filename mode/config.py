import os
import sys

def _get_script_drive():
    """获取EXE或脚本所在的盘符（兼容开发环境和打包后运行）"""
    # 优先判断是否为打包后运行
    if getattr(sys, 'frozen', False):
        # 打包后运行：sys.executable 指向 EXE 文件的绝对路径
        exe_path = sys.executable
        drive = os.path.splitdrive(exe_path)[0]
        if drive:
            return drive
    
    # 开发环境运行：使用 __file__ 获取脚本所在目录
    try:
        script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        drive = os.path.splitdrive(script_dir)[0]
        if drive:
            return drive
    except:
        pass
    
    # 兜底：使用当前工作目录
    cwd = os.getcwd()
    drive = os.path.splitdrive(cwd)[0]
    if drive:
        return drive
    
    # 最终兜底
    return "D:"

SCRIPT_DRIVE = _get_script_drive()
ROOT_DIR = os.path.join(SCRIPT_DRIVE + os.sep, "ROOT")

DRIVE_LETTER = SCRIPT_DRIVE[0].lower()
DB_NAME = f"private_repo_{DRIVE_LETTER}"

DB_CONFIG = {
    "host": "localhost",
    "port": 3306,
    "user": "root",
    "password": "Root123456",
    "database": DB_NAME,
    "charset": "utf8mb4",
    "autocommit": False,
}

SKIP_DIRS = {"MYSQL_DB"}