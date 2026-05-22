# mode/point.py
"""文件点（Point）管理：扫描入库、移动、列表、删除"""
import os
import hashlib
import pymysql
from .config import ROOT_DIR, SKIP_DIRS
from .database import get_conn
from .flow import get_flow_by_path, get_subflow_ids

def compute_hash(filepath):
    """计算文件 SHA256"""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha256.update(chunk)
    return sha256.hexdigest()

def scan_files():
    """扫描 ROOT 目录，将文件入库（支持多归属，可选仅新文件）"""
    if not os.path.isdir(ROOT_DIR):
        print(f"[错误] 目录 {ROOT_DIR} 不存在！")
        return

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT file_name, flow_id FROM point")
            existing_pairs = set(cur.fetchall())
            all_recorded_files = {row[0] for row in existing_pairs}

        # 收集 ROOT 下的所有文件
        files_on_disk = []
        for item in os.listdir(ROOT_DIR):
            full = os.path.join(ROOT_DIR, item)
            if os.path.isfile(full):
                files_on_disk.append(item)
            elif os.path.isdir(full):
                if item in SKIP_DIRS:
                    continue
                print(f"[警告] 发现子目录 '{item}'，已跳过（请扁平化文件）。")

        if not files_on_disk:
            print("ROOT 下没有文件。")
            return

        # 新增：询问是否只看未入库的新文件
        only_new = input("是否只列出未入库的新文件？(y/n，默认 n)：").strip().lower()
        if only_new == 'y':
            target_files = [f for f in files_on_disk if f not in all_recorded_files]
            if not target_files:
                print("没有未入库的新文件。")
                return
        else:
            target_files = files_on_disk

        print(f"共有 {len(target_files)} 个文件可供入库。")
        if only_new != 'y':
            print("（包含已在其他 Flow 下存在的文件，可添加到新 Flow）")
        print("（输入 q 退出扫描，s 跳过当前文件）")

        for fname in target_files:
            full = os.path.join(ROOT_DIR, fname)
            stat = os.stat(full)
            file_hash = compute_hash(full)
            suffix = fname.rsplit('.', 1)[-1].lower() if '.' in fname else ''

            print(f"\n文件：{fname}  ({stat.st_size:,} 字节)")
            if fname in all_recorded_files and only_new != 'y':
                print("  ℹ 该文件已在其他 Flow 下存在，可添加到新 Flow。")

            flow_input = input("所属 Flow 路径（默认 /ROOT，输入 q 退出，s 跳过）：").strip()
            if flow_input == "q":
                print("用户中断扫描。")
                break
            if flow_input == "s":
                print(f"跳过 {fname}")
                continue

            flow_input = flow_input or "/ROOT"
            try:
                with conn.cursor() as cur:
                    flow_id = get_flow_by_path(cur, flow_input)
                    if (fname, flow_id) in existing_pairs:
                        print(f"  ⚠ 文件已存在于该 Flow，跳过。")
                        continue
                    cur.execute(
                        "INSERT INTO point (flow_id, file_name, file_suffix, file_size, file_hash) "
                        "VALUES (%s,%s,%s,%s,%s)",
                        (flow_id, fname, suffix, stat.st_size, file_hash)
                    )
                conn.commit()
                existing_pairs.add((fname, flow_id))
                all_recorded_files.add(fname)
                print(f"  → 已入库，Flow ID={flow_id}")
            except ValueError as e:
                print(f"路径错误：{e}，跳过。")
            except pymysql.err.IntegrityError:
                conn.rollback()
                print("  × 文件名重复或数据库约束错误，跳过。")
            except Exception as e:
                conn.rollback()
                print(f"  × 入库失败: {e}")
    except Exception as e:
        conn.rollback()
        print(f"[错误] 扫描过程异常: {e}")
    finally:
        conn.close()
    print("\n扫描完成。")

def move_point():
    """移动文件记录：在多归属模式下，可选择移动具体哪一条记录"""
    fname = input("输入要移动的文件名：").strip()
    if not fname:
        return

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT p.point_id, p.file_name, f.flow_name, f.flow_id "
                "FROM point p JOIN flow f ON p.flow_id = f.flow_id "
                "WHERE p.file_name = %s",
                (fname,)
            )
            records = cur.fetchall()
            if not records:
                print("文件未入库。")
                return

            if len(records) == 1:
                selected_pid, selected_fname, current_flow_name, current_flow_id = records[0]
                print(f"该文件当前仅存在于 Flow: {current_flow_name}")
            else:
                print(f"文件 '{fname}' 同时存在于以下 Flow：")
                for i, (pid, fn, flow_name, fid) in enumerate(records, start=1):
                    print(f"  {i}. Flow: {flow_name}")
                choice = input("输入要移动的记录编号：").strip()
                try:
                    idx = int(choice) - 1
                    if idx < 0 or idx >= len(records):
                        print("编号无效。")
                        return
                    selected_pid, selected_fname, current_flow_name, current_flow_id = records[idx]
                except ValueError:
                    print("请输入数字。")
                    return

            new_path = input("输入目标 Flow 路径：").strip()
            if not new_path:
                return
            new_flow_id = get_flow_by_path(cur, new_path)

            # 检查目标 Flow 是否已有同名文件（防止重复）
            cur.execute("SELECT point_id FROM point WHERE file_name=%s AND flow_id=%s", (fname, new_flow_id))
            if cur.fetchone():
                print(f"文件 '{fname}' 已存在于目标 Flow，无法移动。")
                return

            cur.execute("UPDATE point SET flow_id=%s WHERE point_id=%s", (new_flow_id, selected_pid))
            conn.commit()
            print(f"已将记录（ID={selected_pid}）从 '{current_flow_name}' 移动到新 Flow。")
    except Exception as e:
        conn.rollback()
        print(f"错误：{e}")
    finally:
        conn.close()

def list_flow(recursive=False):
    """交互式列出 Flow 下的文件（仅当前层级或递归）"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # 加载所有 Flow
            cur.execute("SELECT flow_id, flow_name, parent_flow_id FROM flow ORDER BY parent_flow_id, flow_name")
            all_flows = {row[0]: {"name": row[1], "parent": row[2]} for row in cur.fetchall()}
            cur.execute("SELECT flow_id FROM flow WHERE flow_name='ROOT' AND parent_flow_id IS NULL")
            root_row = cur.fetchone()
            if not root_row:
                print("错误：根节点缺失")
                return
            current_id = root_row[0]

            while True:
                cur.execute("SELECT flow_name FROM flow WHERE flow_id=%s", (current_id,))
                current_name = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM point WHERE flow_id=%s", (current_id,))
                file_cnt = cur.fetchone()[0]
                print(f"\n当前 Flow: {current_name}  ({file_cnt} 文件)")

                cur.execute("SELECT flow_id, flow_name FROM flow WHERE parent_flow_id=%s ORDER BY flow_name", (current_id,))
                children = cur.fetchall()

                if children:
                    print("子 Flow：")
                    print("  0. [查看当前目录下的文件]")
                    for i, child in enumerate(children, start=1):
                        print(f"  {i}. {child[1]}")
                    print("  b. 返回上级")
                    print("  q. 退出")
                else:
                    print("（没有子 Flow）")
                    print("  0. 查看当前目录下的文件")
                    print("  b. 返回上级")
                    print("  q. 退出")

                choice = input("请选择：").strip().lower()
                if choice == '0':
                    # 显示文件
                    if recursive:
                        all_ids = get_subflow_ids(cur, current_id)
                        format_strings = ','.join(['%s'] * len(all_ids))
                        cur.execute(
                            f"SELECT file_name, file_size, created_at FROM point WHERE flow_id IN ({format_strings}) ORDER BY file_name",
                            all_ids
                        )
                    else:
                        cur.execute(
                            "SELECT file_name, file_size, created_at FROM point WHERE flow_id=%s ORDER BY file_name",
                            (current_id,)
                        )
                    points = cur.fetchall()
                    if not points:
                        print("当前 Flow 下暂无文件。")
                    else:
                        flow_path = _get_flow_path(cur, current_id, all_flows)
                        print(f"\n--- {flow_path} 下的文件 ({len(points)} 个) ---")
                        for fname, size, ctime in points:
                            print(f"  {fname}  ({size/1024/1024:.2f} MB)  入库时间: {ctime}")
                    input("\n按回车键继续...")
                elif choice == 'b':
                    parent_id = all_flows[current_id]["parent"]
                    if parent_id is None:
                        print("已经在根目录。")
                    else:
                        current_id = parent_id
                elif choice == 'q':
                    break
                else:
                    try:
                        idx = int(choice) - 1
                        if 0 <= idx < len(children):
                            current_id = children[idx][0]
                        else:
                            print("无效数字。")
                    except ValueError:
                        print("无效输入。")
    except Exception as e:
        print(f"错误：{e}")
    finally:
        conn.close()

def _get_flow_path(cur, flow_id, flows_cache):
    """根据 flow_id 返回完整路径字符串"""
    parts = []
    while flow_id is not None:
        parts.append(flows_cache[flow_id]["name"])
        flow_id = flows_cache[flow_id]["parent"]
    return "/" + "/".join(reversed(parts))

def delete_point():
    """删除文件记录：支持多归属选择或全部删除，最后一条记录会物理删除"""
    fname = input("输入要删除记录的文件名：").strip()
    if not fname:
        return

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT p.point_id, p.file_name, f.flow_name "
                "FROM point p JOIN flow f ON p.flow_id = f.flow_id "
                "WHERE p.file_name = %s",
                (fname,)
            )
            records = cur.fetchall()
            if not records:
                print("文件未入库，无需删除。")
                return

            if len(records) == 1:
                pid, fn, flow_name = records[0]
                print(f"文件 '{fn}' 当前仅在 Flow '{flow_name}' 中。")
                confirm = input("确定删除这条记录并物理删除文件？(y/n): ").strip().lower()
                if confirm == 'y':
                    phys_path = os.path.join(ROOT_DIR, fn)
                    if os.path.isfile(phys_path):
                        try:
                            os.remove(phys_path)
                            print("  物理文件已删除。")
                        except Exception as e:
                            print(f"  删除物理文件失败：{e}")
                    else:
                        print("  物理文件不存在，仅删除记录。")
                    cur.execute("DELETE FROM point WHERE point_id=%s", (pid,))
                    conn.commit()
                    print("  记录已删除。")
                else:
                    print("已取消。")
            else:
                print(f"文件 '{fname}' 存在于以下 Flow：")
                for i, (pid, fn, flow_name) in enumerate(records, start=1):
                    print(f"  {i}. Flow: {flow_name}")
                print("操作选项：")
                print("  A. 删除所有记录并物理删除文件")
                print("  B. 选择一条记录删除")
                choice = input("请输入 A 或 B：").strip().upper()

                if choice == 'A':
                    confirm = input(
                        f"确定删除 '{fname}' 的全部 {len(records)} 条记录并物理删除文件？(y/n): "
                    ).strip().lower()
                    if confirm == 'y':
                        phys_path = os.path.join(ROOT_DIR, fn)
                        if os.path.isfile(phys_path):
                            try:
                                os.remove(phys_path)
                                print("  物理文件已删除。")
                            except Exception as e:
                                print(f"  删除物理文件失败：{e}")
                        else:
                            print("  物理文件不存在，仅删除记录。")
                        cur.execute("DELETE FROM point WHERE file_name=%s", (fname,))
                        conn.commit()
                        print("  所有记录已删除。")
                    else:
                        print("已取消。")
                elif choice == 'B':
                    sel = input("输入要删除的记录编号：").strip()
                    try:
                        idx = int(sel) - 1
                        if idx < 0 or idx >= len(records):
                            print("编号无效。")
                            return
                        pid, fn, flow_name = records[idx]

                        remaining = len(records) - 1
                        if remaining == 0:
                            confirm = input(
                                f"这是 '{fn}' 的最后一条记录，删除后将物理删除文件，确定吗？(y/n): "
                            ).strip().lower()
                        else:
                            confirm = input(
                                f"还有 {remaining} 个 Flow 引用此文件，"
                                f"仅删除当前记录（保留物理文件），确定吗？(y/n): "
                            ).strip().lower()

                        if confirm == 'y':
                            if remaining == 0:
                                phys_path = os.path.join(ROOT_DIR, fn)
                                if os.path.isfile(phys_path):
                                    try:
                                        os.remove(phys_path)
                                        print("  物理文件已删除。")
                                    except Exception as e:
                                        print(f"  删除物理文件失败：{e}")
                            cur.execute("DELETE FROM point WHERE point_id=%s", (pid,))
                            conn.commit()
                            print("  记录已删除。")
                        else:
                            print("已取消。")
                    except ValueError:
                        print("请输入数字。")
                else:
                    print("无效选择。")
    except Exception as e:
        conn.rollback()
        print(f"错误：{e}")
    finally:
        conn.close()