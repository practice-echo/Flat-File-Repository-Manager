# mode/backup.py
"""数据库备份与恢复：备份为 ROOT 下的文件，并自动归入 Databasebck Flow"""
import os
import pymysql
from datetime import datetime
from .config import ROOT_DIR, DB_CONFIG
from .database import get_conn
from .flow import get_flow_by_path
from .point import compute_hash

def _ensure_backup_flow(cur):
    """确保 /ROOT/Databasebck Flow 存在，返回其 flow_id"""
    try:
        return get_flow_by_path(cur, "/ROOT/Databasebck")
    except:
        # 根节点可能不存在？但初始化时应该有，如果出错则重新抛
        raise

def backup_database():
    """备份当前盘数据库（单库）并自动入库"""
    print("\n--- 备份当前盘数据库 ---")
    conn_db = pymysql.connect(**DB_CONFIG)
    try:
        with conn_db.cursor() as cur:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            db_name = DB_CONFIG.get("database", "private_repo")
            backup_filename = f"database_backup_{db_name}_{timestamp}.sql"
            backup_path = os.path.join(ROOT_DIR, backup_filename)

            # 导出数据
            cur.execute("SHOW TABLES")
            tables = [row[0] for row in cur.fetchall()]
            if not tables:
                print("当前数据库没有表，跳过备份。")
                return

            with open(backup_path, 'w', encoding='utf-8') as f:
                f.write(f"-- Backup of {db_name} created at {timestamp}\n")
                f.write("SET FOREIGN_KEY_CHECKS=0;\n\n")
                for table in tables:
                    cur.execute(f"SHOW CREATE TABLE `{table}`")
                    create_table = cur.fetchone()[1]
                    f.write(f"DROP TABLE IF EXISTS `{table}`;\n")
                    f.write(f"{create_table};\n\n")
                    cur.execute(f"SELECT * FROM `{table}`")
                    rows = cur.fetchall()
                    if rows:
                        columns = [col[0] for col in cur.description]
                        for row in rows:
                            values = []
                            for val in row:
                                if val is None:
                                    values.append("NULL")
                                elif isinstance(val, bytes):
                                    values.append(f"0x{val.hex()}")
                                elif isinstance(val, datetime):
                                    values.append(f"'{val.strftime('%Y-%m-%d %H:%M:%S')}'")
                                else:
                                    escaped = str(val).replace("\\", "\\\\").replace("'", "\\'")
                                    values.append(f"'{escaped}'")
                            f.write(f"INSERT INTO `{table}` (`{'`, `'.join(columns)}`) VALUES ({', '.join(values)});\n")
                        f.write("\n")
                f.write("SET FOREIGN_KEY_CHECKS=1;\n")
            print(f"备份文件已生成：{backup_path}")

            # 入库：将备份文件添加到 Flow
            stat = os.stat(backup_path)
            file_hash = compute_hash(backup_path)
            suffix = "sql"

            conn_repo = get_conn()
            try:
                with conn_repo.cursor() as cur_repo:
                    flow_id = _ensure_backup_flow(cur_repo)
                    # 检查是否已存在同一文件（防止重复入库）
                    cur_repo.execute(
                        "SELECT point_id FROM point WHERE file_name=%s AND flow_id=%s",
                        (backup_filename, flow_id)
                    )
                    if not cur_repo.fetchone():
                        cur_repo.execute(
                            "INSERT INTO point (flow_id, file_name, file_suffix, file_size, file_hash) "
                            "VALUES (%s,%s,%s,%s,%s)",
                            (flow_id, backup_filename, suffix, stat.st_size, file_hash)
                        )
                        conn_repo.commit()
                        print(f"备份文件已归入 /ROOT/Databasebck")
                    else:
                        print("文件已在 Databasebck 中存在，跳过入库。")
            except Exception as e:
                print(f"入库失败（备份文件仍保留在 ROOT 下）：{e}")
            finally:
                conn_repo.close()

    except Exception as e:
        print(f"备份出错：{e}")
    finally:
        conn_db.close()

def backup_all_databases():
    """备份所有 private_repo_* 数据库到一个文件，并归入 Databasebck"""
    print("\n--- 备份全部盘数据库 ---")
    base_config = DB_CONFIG.copy()
    db_name = base_config.pop("database", "private_repo")
    try:
        conn = pymysql.connect(**base_config)
        with conn.cursor() as cur:
            cur.execute("SHOW DATABASES LIKE 'private_repo\\_%'")
            databases = [row[0] for row in cur.fetchall()]
            if not databases:
                print("未找到任何 private_repo_* 数据库。")
                return
            print(f"找到 {len(databases)} 个数据库：{', '.join(databases)}")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_filename = f"database_backup_all_{timestamp}.sql"
            backup_path = os.path.join(ROOT_DIR, backup_filename)

            with open(backup_path, 'w', encoding='utf-8') as f:
                f.write(f"-- Full backup of all private_repo_* databases at {timestamp}\n")
                f.write("SET FOREIGN_KEY_CHECKS=0;\n\n")
                for db in databases:
                    f.write(f"\n-- Database: {db}\n")
                    f.write(f"CREATE DATABASE IF NOT EXISTS `{db}` DEFAULT CHARACTER SET utf8mb4;\n")
                    f.write(f"USE `{db}`;\n\n")
                    conn.select_db(db)
                    cur.execute("SHOW TABLES")
                    tables = [row[0] for row in cur.fetchall()]
                    for table in tables:
                        cur.execute(f"SHOW CREATE TABLE `{table}`")
                        create_table = cur.fetchone()[1]
                        f.write(f"DROP TABLE IF EXISTS `{table}`;\n")
                        f.write(f"{create_table};\n\n")
                        cur.execute(f"SELECT * FROM `{table}`")
                        rows = cur.fetchall()
                        if rows:
                            columns = [col[0] for col in cur.description]
                            for row in rows:
                                values = []
                                for val in row:
                                    if val is None:
                                        values.append("NULL")
                                    elif isinstance(val, bytes):
                                        values.append(f"0x{val.hex()}")
                                    elif isinstance(val, datetime):
                                        values.append(f"'{val.strftime('%Y-%m-%d %H:%M:%S')}'")
                                    else:
                                        escaped = str(val).replace("\\", "\\\\").replace("'", "\\'")
                                        values.append(f"'{escaped}'")
                                f.write(f"INSERT INTO `{table}` (`{'`, `'.join(columns)}`) VALUES ({', '.join(values)});\n")
                            f.write("\n")
                f.write("SET FOREIGN_KEY_CHECKS=1;\n")
            print(f"全库备份文件已生成：{backup_path}")

            # 入库
            stat = os.stat(backup_path)
            file_hash = compute_hash(backup_path)
            conn_repo = get_conn()
            try:
                with conn_repo.cursor() as cur_repo:
                    flow_id = _ensure_backup_flow(cur_repo)
                    cur_repo.execute(
                        "SELECT point_id FROM point WHERE file_name=%s AND flow_id=%s",
                        (backup_filename, flow_id)
                    )
                    if not cur_repo.fetchone():
                        cur_repo.execute(
                            "INSERT INTO point (flow_id, file_name, file_suffix, file_size, file_hash) "
                            "VALUES (%s,%s,%s,%s,%s)",
                            (flow_id, backup_filename, "sql", stat.st_size, file_hash)
                        )
                        conn_repo.commit()
                        print("备份文件已归入 /ROOT/Databasebck")
                    else:
                        print("文件已在 Databasebck 中存在，跳过入库。")
            except Exception as e:
                print(f"入库失败：{e}")
            finally:
                conn_repo.close()
    except Exception as e:
        print(f"全库备份出错：{e}")
    finally:
        if 'conn' in locals():
            conn.close()

def restore_database():
    """从备份文件恢复数据库（自动处理数据库不存在的情况）"""
    print("\n--- 恢复数据库 ---")
    sql_files = [f for f in os.listdir(ROOT_DIR) if f.endswith('.sql')]
    if not sql_files:
        print("ROOT 目录下没有找到 .sql 备份文件。")
        return

    print("找到以下备份文件：")
    for i, fname in enumerate(sql_files, start=1):
        print(f"  {i}. {fname}")
    print("  0. 返回")
    choice = input("请选择要恢复的文件编号：").strip()
    if choice == '0':
        return
    try:
        idx = int(choice) - 1
        if idx < 0 or idx >= len(sql_files):
            print("编号无效。")
            return
        selected = sql_files[idx]
    except ValueError:
        print("请输入数字。")
        return

    backup_path = os.path.join(ROOT_DIR, selected)
    confirm = input(f"警告：恢复将覆盖现有数据库！确定从 '{selected}' 恢复吗？(y/n): ").strip().lower()
    if confirm != 'y':
        print("已取消。")
        return

    # 建议先备份当前数据
    backup_first = input("是否先备份当前盘数据库？(y/n): ").strip().lower()
    if backup_first == 'y':
        backup_database()

    # 连接 MySQL 实例（不指定数据库）
    conn_params = DB_CONFIG.copy()
    conn_params.pop("database", None)
    try:
        conn = pymysql.connect(**conn_params)
        with conn.cursor() as cur:
            # 关闭外键检查
            cur.execute("SET FOREIGN_KEY_CHECKS=0")
            
            with open(backup_path, 'r', encoding='utf-8') as f:
                sql_script = f.read()
            statements = sql_script.split(';')
            
            for statement in statements:
                statement = statement.strip()
                if not statement or statement.startswith('--') or statement.startswith('/*'):
                    continue
                
                # 如果是 USE 语句，先确保数据库存在
                if statement.upper().startswith('USE '):
                    db_name = statement[4:].strip().strip('`').strip("'")
                    try:
                        cur.execute(f"CREATE DATABASE IF NOT EXISTS `{db_name}` DEFAULT CHARACTER SET utf8mb4")
                    except:
                        pass
                
                try:
                    cur.execute(statement)
                except pymysql.err.OperationalError as e:
                    if 'Unknown table' in str(e) or "doesn't exist" in str(e):
                        pass  # 忽略表不存在的错误
                    else:
                        print(f"执行语句时出错：{e}\n语句：{statement[:100]}...")
                        raise
            
            # 恢复后重新开启外键检查
            cur.execute("SET FOREIGN_KEY_CHECKS=1")
            conn.commit()
            print(f"数据库已从 '{selected}' 成功恢复。")
    except Exception as e:
        if 'conn' in locals():
            conn.rollback()
        print(f"恢复失败：{e}")
    finally:
        if 'conn' in locals():
            conn.close()