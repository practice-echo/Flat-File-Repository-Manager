from .database import init_db
from .flow import show_tree, create_flow
from .point import scan_files, list_flow
from .import_folder import run_import
from .organizer import organizer_menu, copy_point_to_flow
from .help import show_help
from .backup import backup_database, restore_database
from .config import SCRIPT_DRIVE, DB_NAME, ROOT_DIR  # 导入配置信息


def backup_restore_menu():
    from .backup import backup_database, backup_all_databases, restore_database
    while True:
        print("\n--- 备份与恢复数据库 ---")
        print(f"当前操作数据库：{DB_NAME} (盘符：{SCRIPT_DRIVE})")
        print("1. 备份当前盘数据库")
        print("2. 备份全部盘数据库")
        print("3. 恢复数据库")
        print("0. 返回")
        ch = input("请选择：").strip()
        if ch == '1':
            backup_database()
        elif ch == '2':
            backup_all_databases()
        elif ch == '3':
            restore_database()
        elif ch == '0':
            break
        else:
            print("无效选择。")
        input("\n按回车键继续...")


def menu():
    print("\n" + "="*40)
    print("  私人工具资源仓库 · 管理工具 v2.4")
    print("="*40)
    # 新增：显示当前连接信息
    print(f"  当前盘符：{SCRIPT_DRIVE}")
    print(f"  仓库目录：{ROOT_DIR}")
    print(f"  数据库：{DB_NAME}")
    print("="*40)
    print(" 1. 初始化数据库")
    print(" 2. 显示 Flow 树")
    print(" 3. 扫描 ROOT 并入库 point")
    print(" 4. 创建 Flow")
    print(" 5. 列出Flow下point")
    print(" 6. 列出Flow下所有point")
    print(" 7. 复制point至其他Flow")
    print(" 8. 整理与清理")
    print(" 9. 批量导入旧文件夹")
    print(" 10. 备份与恢复数据库")
    print(" H. 使用帮助")
    print(" 0. 退出")
    return input("请选择：").strip()


def main_loop():
    while True:
        choice = menu()
        if choice == "1":
            init_db()
        elif choice == "2":
            show_tree()
        elif choice == "3":
            scan_files()
        elif choice == "4":
            create_flow()
        elif choice == "5":
            list_flow(recursive=False)
        elif choice == "6":
            list_flow(recursive=True)
        elif choice == "7":
            from .organizer import copy_point_to_flow
            copy_point_to_flow()
        elif choice == "8":
            organizer_menu()
        elif choice == "9":
            run_import()
        elif choice == "10":
            backup_restore_menu()
        elif choice.upper() == "H":
            show_help()
        elif choice == "0":
            print("再见！")
            break
        else:
            print("无效选择，请重新输入。")
        input("\n按回车键继续...")