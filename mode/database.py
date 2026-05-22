# mode/database.py
import os
import subprocess
import time
import pymysql
from .config import DB_CONFIG, ROOT_DIR

def get_conn():
    return pymysql.connect(**DB_CONFIG)

def get_root_id(cur):
    cur.execute("SELECT flow_id FROM flow WHERE flow_name='ROOT' AND parent_flow_id IS NULL")
    row = cur.fetchone()
    if not row:
        raise Exception("根节点 ROOT 缺失，请先执行初始化。")
    return row[0]

def _ensure_mysql_container():
    container_name = "root-repo-mysql"
    mysql_port = DB_CONFIG.get("port", 3306)

    try:
        subprocess.run(["docker", "ps"], capture_output=True, check=True, timeout=10)
    except FileNotFoundError:
        print("[错误] 未检测到 Docker，请先安装 Docker Desktop。")
        return False
    except subprocess.CalledProcessError:
        print("[错误] Docker 命令执行失败，请确认 Docker Desktop 已启动。")
        return False
    except Exception as e:
        print(f"[错误] 无法连接 Docker：{e}")
        return False

    result = subprocess.run(
        ["docker", "ps", "-a", "--format", "{{.Names}}", "--filter", f"name={container_name}"],
        capture_output=True, text=True
    )
    container_exists = container_name in result.stdout.strip().split('\n')

    if container_exists:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}", "--filter", f"name={container_name}"],
            capture_output=True, text=True
        )
        if container_name in result.stdout:
            print(f"[容器] {container_name} 已在运行中。")
            return True
        else:
            print(f"[容器] {container_name} 已存在但未运行，正在启动...")
            try:
                subprocess.run(["docker", "start", container_name], check=True, timeout=30)
                print(f"[容器] {container_name} 启动成功。")
                return True
            except Exception as e:
                print(f"[错误] 无法启动容器 {container_name}：{e}")
                return False
    else:
        drive = os.path.splitdrive(ROOT_DIR)[0]
        volume_path = os.path.join(drive + os.sep, "ROOT", "MYSQL_DB")
        os.makedirs(volume_path, exist_ok=True)
        print(f"[容器] 正在创建 {container_name}，数据目录：{volume_path}")
        cmd = [
            "docker", "run", "-d",
            "--name", container_name,
            "-p", f"{mysql_port}:3306",
            "-e", "MYSQL_ROOT_PASSWORD=Root123456",
            "-v", f"{volume_path}:/var/lib/mysql",
            "--restart", "always",
            "mysql:8.0"
        ]
        try:
            subprocess.run(cmd, check=True, timeout=60)
            print(f"[容器] {container_name} 创建并启动成功。")
            return True
        except Exception as e:
            print(f"[错误] 创建容器失败：{e}")
            return False

def init_db():
    print("[初始化] 正在检查 MySQL 容器...")
    if not _ensure_mysql_container():
        print("[初始化] MySQL 容器未能就绪，初始化中止。")
        return

    base_config = DB_CONFIG.copy()
    db_name = base_config.pop("database", "private_repo")

    # 等待 MySQL 服务就绪
    print("[初始化] 等待 MySQL 服务就绪...")
    max_retries = 30
    for i in range(max_retries):
        try:
            conn = pymysql.connect(**base_config)
            conn.ping()
            conn.close()
            break
        except Exception:
            if i < max_retries - 1:
                time.sleep(2)
            else:
                print("[错误] MySQL 服务长时间未就绪，请检查容器日志。")
                return

    # 检查是否已初始化
    try:
        conn = pymysql.connect(**base_config)
        with conn.cursor() as cur:
            cur.execute(f"SELECT SCHEMA_NAME FROM INFORMATION_SCHEMA.SCHEMATA WHERE SCHEMA_NAME = '{db_name}'")
            if cur.fetchone():
                conn.select_db(db_name)
                cur.execute("SELECT flow_id FROM flow WHERE flow_name='ROOT' AND parent_flow_id IS NULL")
                if cur.fetchone():
                    print(f"[提示] 数据库 '{db_name}' 已初始化过，根节点已存在，无需重复执行。")
                    confirm = input("是否仍要重新初始化（不会覆盖现有数据）？(y/n): ").strip().lower()
                    if confirm != 'y':
                        conn.close()
                        return
        conn.close()
    except pymysql.err.OperationalError:
        pass

    # 确保数据库存在
    try:
        conn = pymysql.connect(**base_config)
        with conn.cursor() as cur:
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{db_name}` DEFAULT CHARACTER SET utf8mb4")
        conn.close()
    except Exception as e:
        print(f"[错误] 无法连接 MySQL：{e}")
        return

    # 建表、插根节点
    try:
        conn = pymysql.connect(database=db_name, **base_config)
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS flow (
                    flow_id         INT PRIMARY KEY AUTO_INCREMENT,
                    flow_name       VARCHAR(100) NOT NULL,
                    parent_flow_id  INT NULL,
                    flow_type       VARCHAR(50),
                    flow_desc       TEXT,
                    flow_tags       VARCHAR(200),
                    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY uk_flow_name_parent (flow_name, parent_flow_id),
                    INDEX idx_parent (parent_flow_id),
                    FOREIGN KEY (parent_flow_id) REFERENCES flow(flow_id) ON DELETE CASCADE
                ) ENGINE=InnoDB
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS point (
                    point_id    INT PRIMARY KEY AUTO_INCREMENT,
                    flow_id     INT NOT NULL,
                    file_name   VARCHAR(255) NOT NULL,
                    file_suffix VARCHAR(30),
                    file_size   BIGINT,
                    file_hash   CHAR(64) NOT NULL,
                    point_note  VARCHAR(200),
                    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY uk_file_flow (file_name, flow_id),
                    INDEX idx_flow (flow_id),
                    INDEX idx_suffix (file_suffix),
                    FOREIGN KEY (flow_id) REFERENCES flow(flow_id) ON DELETE CASCADE
                ) ENGINE=InnoDB
            """)
            root_desc = f"物理仓库 {ROOT_DIR} 的总入口"
            cur.execute("""
                INSERT INTO flow (flow_name, parent_flow_id, flow_type, flow_desc, flow_tags)
                SELECT 'ROOT', NULL, '根节点', %s, '系统,总根'
                WHERE NOT EXISTS (SELECT 1 FROM flow WHERE flow_name='ROOT' AND parent_flow_id IS NULL)
            """, (root_desc,))
            conn.commit()
            print(f"[初始化] 数据库 '{db_name}' 及表结构已就绪，根节点已存在。")
    except Exception as e:
        if 'conn' in locals():
            conn.rollback()
        print(f"[错误] 初始化失败：{e}")
    finally:
        if 'conn' in locals():
            conn.close()