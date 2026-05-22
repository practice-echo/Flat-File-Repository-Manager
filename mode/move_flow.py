# mode/move_flow.py
"""将整个 Flow（含子 Flow 和所有文件）物理移出仓库，并自动创建对应文件夹"""
import os
import shutil
from .config import ROOT_DIR
from .database import get_conn
from .flow import get_subflow_ids

def _select_flow_interactively():
    """交互式选择 Flow，返回 (flow_id, flow_path_str, flow_name) 或 (None, None, None) 退出"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT flow_id, flow_name, parent_flow_id FROM flow ORDER BY parent_flow_id, flow_name")
            all_flows = {row[0]: {"name": row[1], "parent": row[2]} for row in cur.fetchall()}
            cur.execute("SELECT flow_id FROM flow WHERE flow_name='ROOT' AND parent_flow_id IS NULL")
            root_row = cur.fetchone()
            if not root_row:
                print("错误：根节点缺失")
                return None, None, None
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
                    path = _get_flow_path(cur, current_id, all_flows)
                    return current_id, path, current_name
                elif choice == 'b':
                    parent = all_flows[current_id]["parent"]
                    if parent is None:
                        print("已在根目录。")
                    else:
                        current_id = parent
                elif choice == 'q':
                    return None, None, None
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
    parts = []
    while flow_id is not None:
        parts.append(flows_cache[flow_id]["name"])
        flow_id = flows_cache[flow_id]["parent"]
    return "/" + "/".join(reversed(parts))

def _gather_all_files(cur, flow_id):
    """递归收集该 Flow 及其所有子 Flow 下的所有文件名"""
    all_ids = get_subflow_ids(cur, flow_id)
    if not all_ids:
        return []
    format_strings = ','.join(['%s'] * len(all_ids))
    cur.execute(
        f"SELECT file_name FROM point WHERE flow_id IN ({format_strings})",
        all_ids
    )
    return [row[0] for row in cur.fetchall()]

def move_flow_out():
    """移出整个 Flow（物理剪切 + 自动创建 Flow 名文件夹 + 级联清理数据库）"""
    print("\n--- 移出 Flow（物理剪切，交互式选择） ---")
    flow_id, flow_path, flow_name = _select_flow_interactively()
    if flow_id is None:
        print("已取消。")
        return

    if flow_path == "/ROOT":
        print("不能移出根节点 ROOT！")
        return

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            files = _gather_all_files(cur, flow_id)
            if not files:
                print("该 Flow 及其子 Flow 下没有文件，无需移出。")
                return

            print(f"\n选中的 Flow：{flow_path}  (名称: {flow_name})")
            print(f"共包含 {len(files)} 个文件（含子 Flow）。")

            # 输入目标基础目录
            base_dest = input("输入目标基础路径（如 D:\\备份，将在此路径下创建文件夹）：").strip()
            if not base_dest or not os.path.isabs(base_dest):
                print("必须提供有效的绝对路径。")
                return
            base_dest = os.path.normpath(base_dest)
            os.makedirs(base_dest, exist_ok=True)

            # 自动创建以 Flow 名命名的子文件夹（若已存在则加后缀）
            dest_dir = os.path.join(base_dest, flow_name)
            if os.path.exists(dest_dir):
                counter = 1
                while True:
                    new_name = f"{flow_name}_{counter}"
                    new_dir = os.path.join(base_dest, new_name)
                    if not os.path.exists(new_dir):
                        dest_dir = new_dir
                        print(f"目标文件夹已存在，改为：{new_dir}")
                        break
                    counter += 1
            os.makedirs(dest_dir, exist_ok=True)

            confirm = input(
                f"将把以上 {len(files)} 个文件移动到 {dest_dir}，"
                "并级联删除数据库中的 Flow 及所有子节点和记录，确定吗？(y/n): "
            ).strip().lower()
            if confirm != 'y':
                print("已取消。")
                return

            # 移动所有物理文件
            moved = 0
            for fname in files:
                src = os.path.join(ROOT_DIR, fname)
                dst = os.path.join(dest_dir, fname)
                if not os.path.isfile(src):
                    print(f"  ⚠ 物理文件缺失: {fname}")
                    continue
                try:
                    shutil.move(src, dst)
                    moved += 1
                    print(f"  ✓ {fname}")
                except Exception as e:
                    print(f"  ✗ 移动失败 {fname}: {e}")

            print(f"移动完成：{moved}/{len(files)} 个文件。")

            # 级联删除数据库 Flow（及子节点、point 记录）
            cur.execute("DELETE FROM flow WHERE flow_id=%s", (flow_id,))
            conn.commit()
            print(f"已从数据库中移除 Flow '{flow_path}' 及其所有子 Flow 和文件记录。")

    except Exception as e:
        conn.rollback()
        print(f"操作出错：{e}")
    finally:
        conn.close()

    input("\n按回车键继续...")