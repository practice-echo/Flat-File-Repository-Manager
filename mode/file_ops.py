# mode/file_ops.py
"""物理文件管理：通过 Flow 导航进行删除/移出"""
import os
import shutil
from .config import ROOT_DIR
from .database import get_conn
from .flow import get_flow_by_path, get_subflow_ids

def _select_flow_interactively():
    """
    交互式选择 Flow，返回 (flow_id, flow_path_str)
    用户用数字层层进入，按 0 选中当前目录，按 b/q 退出
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # 加载全部 Flow 数据
            cur.execute("SELECT flow_id, flow_name, parent_flow_id FROM flow ORDER BY parent_flow_id, flow_name")
            all_flows = {row[0]: {"name": row[1], "parent": row[2]} for row in cur.fetchall()}
            # 根节点
            cur.execute("SELECT flow_id FROM flow WHERE flow_name='ROOT' AND parent_flow_id IS NULL")
            root_row = cur.fetchone()
            if not root_row:
                print("错误：根节点缺失")
                return None, None
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
                    print("  0. [选中当前目录]")
                    for i, child in enumerate(children, start=1):
                        print(f"  {i}. {child[1]}")
                    print("  b. 返回上级")
                    print("  q. 退出")
                else:
                    print("（没有子 Flow）")
                    print("  0. 选中当前目录")
                    print("  b. 返回上级")
                    print("  q. 退出")

                choice = input("请选择：").strip().lower()
                if choice == '0':
                    # 返回当前 Flow ID 及路径字符串
                    path = _get_flow_path(cur, current_id, all_flows)
                    return current_id, path
                elif choice == 'b':
                    parent = all_flows[current_id]["parent"]
                    if parent is None:
                        print("已在根目录。")
                    else:
                        current_id = parent
                elif choice == 'q':
                    return None, None
                else:
                    try:
                        idx = int(choice) - 1
                        if 0 <= idx < len(children):
                            current_id = children[idx][0]
                        else:
                            print("无效数字。")
                    except ValueError:
                        print("无效输入。")
    finally:
        conn.close()

def _get_flow_path(cur, flow_id, flows_cache):
    """构造完整路径字符串"""
    parts = []
    while flow_id is not None:
        parts.append(flows_cache[flow_id]["name"])
        flow_id = flows_cache[flow_id]["parent"]
    return "/" + "/".join(reversed(parts))

def _delete_files(cur, conn, file_list):
    """批量删除物理文件及数据库记录"""
    for fname in file_list:
        full = os.path.join(ROOT_DIR, fname)
        if os.path.isfile(full):
            try:
                os.remove(full)
                print(f"  ✓ 已删除: {fname}")
            except Exception as e:
                print(f"  ✗ 删除失败: {fname} - {e}")
        else:
            print(f"  ⚠ 物理文件缺失: {fname}")
        cur.execute("DELETE FROM point WHERE file_name=%s", (fname,))
    conn.commit()

def _move_files(cur, conn, file_list, dest_dir):
    """批量移动物理文件到 dest_dir，并删除数据库记录"""
    os.makedirs(dest_dir, exist_ok=True)
    for fname in file_list:
        src = os.path.join(ROOT_DIR, fname)
        if not os.path.isfile(src):
            print(f"  ⚠ 物理文件缺失: {fname}")
            cur.execute("DELETE FROM point WHERE file_name=%s", (fname,))
            continue
        dst = os.path.join(dest_dir, fname)
        # 处理重名
        if os.path.exists(dst):
            base, ext = os.path.splitext(fname)
            counter = 1
            while True:
                new_name = f"{base}_{counter}{ext}"
                new_dst = os.path.join(dest_dir, new_name)
                if not os.path.exists(new_dst):
                    dst = new_dst
                    break
                counter += 1
            print(f"  目标已存在同名文件，重命名为: {os.path.basename(dst)}")
        try:
            shutil.move(src, dst)
            print(f"  ✓ 已移至: {dst}")
        except Exception as e:
            print(f"  ✗ 移动失败: {fname} - {e}")
            continue
        cur.execute("DELETE FROM point WHERE file_name=%s", (fname,))
    conn.commit()

def manage_files():
    """通过 Flow 导航管理物理文件"""
    print("\n--- 物理文件管理（基于 Flow 导航） ---")
    flow_id, flow_path = _select_flow_interactively()
    if flow_id is None:
        print("已取消。")
        return

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT file_name FROM point WHERE flow_id=%s ORDER BY file_name", (flow_id,))
            files = [row[0] for row in cur.fetchall()]

            if not files:
                print(f"Flow '{flow_path}' 下没有文件。")
                return

            print(f"\nFlow: {flow_path}  (共 {len(files)} 个文件)")
            for i, fname in enumerate(files, start=1):
                print(f"  {i:3d}. {fname}")

            print("\n操作选项：")
            print("  1. 删除全部文件（物理 + 记录）")
            print("  2. 移出全部文件（移动到指定文件夹 + 删除记录）")
            print("  3. 按编号选择文件并删除")
            print("  4. 按编号选择文件并移出")
            print("  0. 返回")
            op = input("请选择：").strip()

            if op == '0':
                return
            if op == '1':
                if input(f"确认删除 {flow_path} 下全部 {len(files)} 个文件？(y/n): ").strip().lower() == 'y':
                    _delete_files(cur, conn, files)
                else:
                    print("已取消。")
            elif op == '2':
                dest = input("输入目标文件夹路径：").strip()
                if not dest or not os.path.isabs(dest):
                    print("必须提供有效的绝对路径。")
                    return
                if input(f"确认移动 {flow_path} 下全部 {len(files)} 个文件到 {dest} ？(y/n): ").strip().lower() == 'y':
                    _move_files(cur, conn, files, dest)
                else:
                    print("已取消。")
            elif op in ('3', '4'):
                sel = input("输入要操作的文件编号（如 1,3,5 或 2-4）：").strip()
                indices = set()
                try:
                    for part in sel.split(','):
                        part = part.strip()
                        if '-' in part:
                            start, end = part.split('-')
                            indices.update(range(int(start), int(end)+1))
                        else:
                            indices.add(int(part))
                except ValueError:
                    print("编号格式错误。")
                    return
                selected = [files[i-1] for i in sorted(indices) if 1 <= i <= len(files)]
                if not selected:
                    print("未选中有效文件。")
                    return
                print(f"将操作 {len(selected)} 个文件：")
                for fname in selected:
                    print(f"  {fname}")
                if op == '3':
                    if input("确认删除以上文件？(y/n): ").strip().lower() == 'y':
                        _delete_files(cur, conn, selected)
                    else:
                        print("已取消。")
                else:
                    dest = input("输入目标文件夹路径：").strip()
                    if not dest or not os.path.isabs(dest):
                        print("路径无效。")
                        return
                    if input(f"确认移动以上文件到 {dest} ？(y/n): ").strip().lower() == 'y':
                        _move_files(cur, conn, selected, dest)
                    else:
                        print("已取消。")
            else:
                print("无效选择。")
    except Exception as e:
        conn.rollback()
        print(f"操作出错：{e}")
    finally:
        conn.close()

    input("\n按回车键继续...")