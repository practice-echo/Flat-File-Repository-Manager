# mode/import_folder.py
"""批量导入旧文件夹到 ROOT 仓库"""
import os
import shutil
import pymysql
from .config import ROOT_DIR, DB_CONFIG
from .database import get_conn, get_root_id
from .flow import get_flow_by_path
from .point import compute_hash

SKIP_FILES = {"Thumbs.db", "desktop.ini", ".DS_Store"}

def _move_to_root(src_path, filename):
    """将文件移动到 ROOT_DIR，重名时自动添加序号，返回最终文件名"""
    dest_path = os.path.join(ROOT_DIR, filename)
    if not os.path.exists(dest_path):
        shutil.move(src_path, dest_path)
        return filename
    base, ext = os.path.splitext(filename)
    counter = 1
    while True:
        new_name = f"{base}_{counter}{ext}"
        new_path = os.path.join(ROOT_DIR, new_name)
        if not os.path.exists(new_path):
            shutil.move(src_path, new_path)
            print(f"  [注意] 文件名冲突，重命名为 {new_name}")
            return new_name
        counter += 1

def run_import(source_dir=None):
    """
    执行批量导入。
    source_dir: 要导入的旧文件夹路径，若不传则在交互中输入。
    """
    if source_dir is None:
        source_dir = input("请输入旧文件夹的完整路径：").strip()
        if not source_dir:
            print("路径不能为空。")
            return

    source_dir = os.path.abspath(source_dir)
    if not os.path.isdir(source_dir):
        print(f"[错误] 源目录 {source_dir} 不存在！")
        return
    if not os.path.isdir(ROOT_DIR):
        print(f"[错误] 物理仓库 {ROOT_DIR} 不存在！")
        return

    print(f"源目录：{source_dir}")
    print(f"目标仓库：{ROOT_DIR}")
    confirm = input("确认开始导入？文件将被移动到 ROOT 目录 (y/n): ").strip().lower()
    if confirm != 'y':
        print("已取消。")
        return

    conn = get_conn()
    cur = conn.cursor()
    total_files = 0

    try:
        for root, dirs, files in os.walk(source_dir):
            # 当前目录相对源目录的路径
            rel_path = os.path.relpath(root, source_dir)
            if rel_path == ".":
                flow_parts = []
            else:
                flow_parts = rel_path.split(os.sep)

            if not files:
                continue   # 空目录不创建 Flow

            # 构造 Flow 路径（/ROOT/...）
            flow_path = "/ROOT"
            if flow_parts:
                flow_path = "/ROOT/" + "/".join(flow_parts)

            # 确保 Flow 存在（包括父级）
            flow_id = get_flow_by_path(cur, flow_path)

            for fname in files:
                if fname in SKIP_FILES:
                    continue
                src_file = os.path.join(root, fname)
                if not os.path.isfile(src_file):
                    continue

                # 移动文件到 ROOT
                new_name = _move_to_root(src_file, fname)
                full_new_path = os.path.join(ROOT_DIR, new_name)

                # 计算哈希、大小
                stat = os.stat(full_new_path)
                file_hash = compute_hash(full_new_path)
                suffix = new_name.rsplit('.', 1)[-1].lower() if '.' in new_name else ''

                # 写入 point 表
                try:
                    cur.execute(
                        "INSERT INTO point (flow_id, file_name, file_suffix, file_size, file_hash) "
                        "VALUES (%s,%s,%s,%s,%s)",
                        (flow_id, new_name, suffix, stat.st_size, file_hash)
                    )
                    conn.commit()
                    total_files += 1
                    flow_display = '/'.join(flow_parts) if flow_parts else 'ROOT'
                    print(f"  ✓ {new_name} -> {flow_display}")
                except pymysql.err.IntegrityError:
                    conn.rollback()
                    print(f"  × {new_name} 入库失败（可能文件名重复），已跳过。")
                except Exception as e:
                    conn.rollback()
                    print(f"  × {new_name} 错误：{e}")

        print(f"\n导入完成！共处理 {total_files} 个文件。")
        print(f"所有文件已移动至 {ROOT_DIR}，原文件夹 {source_dir} 中的文件已移空。")
        print("建议手动删除空的旧文件夹结构。")
    except Exception as e:
        conn.rollback()
        print(f"[严重错误] 导入过程异常: {e}")
    finally:
        cur.close()
        conn.close()