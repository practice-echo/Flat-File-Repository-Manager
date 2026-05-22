# mode/organizer.py
"""整理与清理：删除、导出、清理悬空文件"""
import os
import shutil
from .config import ROOT_DIR
from .database import get_conn
from .flow import get_flow_by_path, get_subflow_ids
from .point import delete_point as delete_point_func

def _gather_all_files(cur, flow_id):
    all_ids = get_subflow_ids(cur, flow_id)
    if not all_ids:
        return []
    format_strings = ','.join(['%s'] * len(all_ids))
    cur.execute(
        f"SELECT file_name FROM point WHERE flow_id IN ({format_strings})",
        all_ids
    )
    return [row[0] for row in cur.fetchall()]

def delete_flow_with_files():
    """删除 Flow：交互式选择，可选择是否删除物理文件"""
    print("\n--- 删除 Flow ---")
    # 使用交互式选择 Flow
    flow_id, flow_path, flow_name = _select_flow_interactively()
    if not flow_id:
        return
    if flow_path == "/ROOT":
        print("不能删除根节点 ROOT！")
        return

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            files = _gather_all_files(cur, flow_id)
            if files:
                print(f"该 Flow 及其子 Flow 共包含 {len(files)} 个文件。")
            else:
                print("该 Flow 及其子 Flow 下没有文件。")

            # 关键：询问是否删除物理文件
            if files:
                del_physical = input("是否同时永久删除所有关联的物理文件？(y/n，默认 y)：").strip().lower()
                if del_physical == 'n':
                    confirm = input(f"将仅删除数据库记录（保留物理文件），确定删除 Flow '{flow_path}' 及其所有子 Flow 吗？(y/n): ").strip().lower()
                else:
                    confirm = input(f"将删除数据库记录并永久删除所有关联物理文件，确定吗？(y/n): ").strip().lower()
            else:
                confirm = input(f"确定删除空 Flow '{flow_path}'？(y/n): ").strip().lower()
                del_physical = 'n'  # 空 Flow 没有文件，无需删除物理文件

            if confirm != 'y':
                print("已取消。")
                return

            # 删除物理文件（如果需要）
            if files and del_physical != 'n':
                for fname in files:
                    full = os.path.join(ROOT_DIR, fname)
                    if os.path.isfile(full):
                        try:
                            os.remove(full)
                            print(f"  已删除物理文件 {fname}")
                        except Exception as e:
                            print(f"  删除物理文件失败 {fname}: {e}")

            # 级联删除 Flow（point 记录会由外键自动删除，或我们主动删除）
            cur.execute("DELETE FROM flow WHERE flow_id=%s", (flow_id,))
            conn.commit()
            print(f"Flow '{flow_path}' 及其所有子 Flow、文件记录已删除。")
            if files and del_physical == 'n':
                print("物理文件已保留。")
    except Exception as e:
        conn.rollback()
        print(f"错误：{e}")
    finally:
        conn.close()

def _select_flow_interactively():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT flow_id, flow_name, parent_flow_id FROM flow ORDER BY parent_flow_id, flow_name")
            all_flows = {row[0]: {"name": row[1], "parent": row[2]} for row in cur.fetchall()}
            cur.execute("SELECT flow_id FROM flow WHERE flow_name='ROOT' AND parent_flow_id IS NULL")
            root = cur.fetchone()
            if not root:
                print("错误：根节点缺失")
                return None, None, None
            current_id = root[0]
            while True:
                cur.execute("SELECT flow_name FROM flow WHERE flow_id=%s", (current_id,))
                cname = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM point WHERE flow_id=%s", (current_id,))
                cnt = cur.fetchone()[0]
                print(f"\n当前 Flow: {cname}  ({cnt} 文件)")
                cur.execute("SELECT flow_id, flow_name FROM flow WHERE parent_flow_id=%s ORDER BY flow_name", (current_id,))
                children = cur.fetchall()
                if children:
                    print("子 Flow：")
                    print("  0. [选中当前目录]")
                    for i, (cid, cnm) in enumerate(children, start=1):
                        print(f"  {i}. {cnm}")
                    print("  b. 返回上级  q. 退出")
                else:
                    print("  0. 选中当前目录  b. 返回上级  q. 退出")
                ch = input("请选择：").strip().lower()
                if ch == '0':
                    path = _get_flow_path(cur, current_id, all_flows)
                    return current_id, path, cname
                elif ch == 'b':
                    p = all_flows[current_id]["parent"]
                    if p is None:
                        print("已在根目录。")
                    else:
                        current_id = p
                elif ch == 'q':
                    return None, None, None
                else:
                    try:
                        idx = int(ch) - 1
                        if 0 <= idx < len(children):
                            current_id = children[idx][0]
                        else:
                            print("无效数字。")
                    except ValueError:
                        print("无效输入。")
    finally:
        conn.close()

def _get_flow_path(cur, fid, flows):
    parts = []
    while fid is not None:
        parts.append(flows[fid]["name"])
        fid = flows[fid]["parent"]
    return "/" + "/".join(reversed(parts))

def export_flow_recursive(flow_id, flow_path, flow_name):
    """递归导出 Flow（含所有子 Flow，保持目录结构）"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            all_ids = get_subflow_ids(cur, flow_id)
            if not all_ids:
                print(f"Flow '{flow_path}' 下没有文件。")
                return
            format_strings = ','.join(['%s'] * len(all_ids))
            cur.execute(
                f"SELECT p.file_name, f.flow_id FROM point p JOIN flow f ON p.flow_id = f.flow_id WHERE p.flow_id IN ({format_strings})",
                all_ids
            )
            files_data = cur.fetchall()
            if not files_data:
                print(f"Flow '{flow_path}' 下没有文件。")
                return
            default_dest = os.path.join(os.path.expanduser("~"), "Desktop", flow_name)
            dest = input(f"目标文件夹路径（回车=桌面\\{flow_name}）：").strip()
            dest = dest if dest else default_dest
            if not os.path.isabs(dest):
                print("请使用绝对路径。")
                return
            dest_dir = os.path.normpath(dest)
            os.makedirs(dest_dir, exist_ok=True)
            print(f"正在导出 {len(files_data)} 个文件到 {dest_dir} ...")
            cur.execute("SELECT flow_id, flow_name, parent_flow_id FROM flow")
            flows = {row[0]: {"name": row[1], "parent": row[2]} for row in cur.fetchall()}
            for fname, fid in files_data:
                src = os.path.join(ROOT_DIR, fname)
                if fid == flow_id:
                    dst = os.path.join(dest_dir, fname)
                else:
                    parts = []
                    tmp = fid
                    while tmp != flow_id:
                        parts.append(flows[tmp]["name"])
                        tmp = flows[tmp]["parent"]
                    parts.reverse()
                    sub = os.path.join(dest_dir, *parts)
                    os.makedirs(sub, exist_ok=True)
                    dst = os.path.join(sub, fname)
                if os.path.isfile(src):
                    shutil.copy2(src, dst)
                    print(f"  ✓ {fname}")
                else:
                    print(f"  ⚠ 缺失: {fname}")
            print(f"导出完成：{dest_dir}")
            if os.name == 'nt':
                os.startfile(dest_dir)
    except Exception as e:
        print(f"导出出错：{e}")
    finally:
        conn.close()

def batch_export_all():
    """批量导出所有有文件的 Flow（完整树形结构）"""
    print("\n--- 批量导出全部 Flow（递归） ---")
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT f.flow_id, f.flow_name, f.parent_flow_id, COUNT(p.point_id)
                FROM flow f JOIN point p ON f.flow_id = p.flow_id
                GROUP BY f.flow_id, f.flow_name, f.parent_flow_id
            """)
            flows = cur.fetchall()
            if not flows:
                print("没有包含文件的 Flow。")
                return
            print(f"共 {len(flows)} 个有文件的 Flow。")
            base = input("输入目标基础路径（如 D:\\完整备份）：").strip()
            if not base or not os.path.isabs(base):
                print("需要绝对路径。")
                return
            base = os.path.normpath(base)
            os.makedirs(base, exist_ok=True)
            cur.execute("SELECT flow_id, flow_name, parent_flow_id FROM flow")
            all_flows = {row[0]: {"name": row[1], "parent": row[2]} for row in cur.fetchall()}
            for fid, fname, pid, cnt in flows:
                parts = []
                cur_id = fid
                while cur_id is not None:
                    parts.append(all_flows[cur_id]["name"])
                    cur_id = all_flows[cur_id]["parent"]
                parts.reverse()
                rel = "/".join(parts[1:]) if len(parts) > 1 else "ROOT"
                dest = os.path.join(base, rel.replace("/", os.sep))
                os.makedirs(dest, exist_ok=True)
                cur.execute("SELECT file_name FROM point WHERE flow_id=%s", (fid,))
                for row in cur.fetchall():
                    src = os.path.join(ROOT_DIR, row[0])
                    if os.path.isfile(src):
                        shutil.copy2(src, os.path.join(dest, row[0]))
                print(f"  ✓ {rel} ({cnt} 文件)")
            print(f"导出完成：{base}")
    except Exception as e:
        print(f"错误：{e}")
    finally:
        conn.close()

def clean_dangling_files():
    """清理悬空文件（不在数据库中的物理文件）"""
    print("\n--- 清理悬空文件 ---")
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT file_name FROM point")
            recorded = {row[0] for row in cur.fetchall()}
    except:
        return
    finally:
        conn.close()
    all_files = [f for f in os.listdir(ROOT_DIR) if os.path.isfile(os.path.join(ROOT_DIR, f))]
    dangling = [f for f in all_files if f not in recorded]
    if not dangling:
        print("没有悬空文件。")
        return
    print(f"发现 {len(dangling)} 个悬空文件。")
    for i, f in enumerate(dangling, 1):
        sz = os.path.getsize(os.path.join(ROOT_DIR, f))
        print(f"  {i:3d}. {f}  ({sz/1024/1024:.2f} MB)")
    print("1. 删除所有  2. 移出所有  3. 按编号删除  4. 按编号移出  0. 返回")
    c = input("请选择：").strip()
    if c == '0': return
    if c in ('1','2'):
        if c == '1':
            if input("永久删除所有悬空文件？(y/n): ").strip().lower() == 'y':
                for f in dangling:
                    try: os.remove(os.path.join(ROOT_DIR, f))
                    except: pass
                print("已删除。")
        else:
            dest = input("目标文件夹：").strip()
            if not dest or not os.path.isabs(dest):
                print("无效路径。"); return
            os.makedirs(dest, exist_ok=True)
            if input(f"移动所有悬空文件到 {dest}？(y/n): ").strip().lower() == 'y':
                for f in dangling:
                    try: shutil.move(os.path.join(ROOT_DIR, f), os.path.join(dest, f))
                    except: pass
                print("已移出。")
    elif c in ('3','4'):
        sel = input("编号（如 1,3,5 或 2-4）：").strip()
        idxs = set()
        for p in sel.split(','):
            p = p.strip()
            if '-' in p:
                a,b = p.split('-',1); idxs.update(range(int(a), int(b)+1))
            else:
                idxs.add(int(p))
        selected = [dangling[i-1] for i in sorted(idxs) if 1 <= i <= len(dangling)]
        if not selected: return
        if c == '3':
            if input("确认删除？(y/n): ").strip().lower() == 'y':
                for f in selected:
                    try: os.remove(os.path.join(ROOT_DIR, f))
                    except: pass
        else:
            dest = input("目标文件夹：").strip()
            if not os.path.isabs(dest): return
            os.makedirs(dest, exist_ok=True)
            if input("确认移动？(y/n): ").strip().lower() == 'y':
                for f in selected:
                    try: shutil.move(os.path.join(ROOT_DIR, f), os.path.join(dest, f))
                    except: pass

def export_selected_points():
    """按编号选择当前 Flow 下的部分文件导出"""
    fid, path, name = _select_flow_interactively()
    if not fid: return
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT file_name FROM point WHERE flow_id=%s ORDER BY file_name", (fid,))
            files = [row[0] for row in cur.fetchall()]
            if not files: return
            print(f"\nFlow: {path}  ({len(files)} 文件)")
            for i, f in enumerate(files,1): print(f"  {i:3d}. {f}")
            sel = input("编号（如 1,3,5 或 2-4）：").strip()
            idxs = set()
            for p in sel.split(','):
                p=p.strip()
                if '-' in p:
                    a,b = p.split('-',1); idxs.update(range(int(a), int(b)+1))
                else:
                    idxs.add(int(p))
            chosen = [files[i-1] for i in sorted(idxs) if 1 <= i <= len(files)]
            if not chosen: return
            dest = input(f"目标文件夹（回车=桌面\\{name}）：").strip()
            if not dest:
                dest = os.path.join(os.path.expanduser("~"), "Desktop", name)
            elif not os.path.isabs(dest):
                print("需要绝对路径。"); return
            os.makedirs(dest, exist_ok=True)
            for f in chosen:
                src = os.path.join(ROOT_DIR, f)
                if os.path.isfile(src):
                    shutil.copy2(src, os.path.join(dest, f))
            print(f"完成：{dest}")
            if os.name == 'nt': os.startfile(dest)
    except Exception as e:
        print(f"错误：{e}")
    finally:
        conn.close()

def copy_point_to_flow():
    """将现有文件记录复制到另一个 Flow（实现多归属）"""
    fid, path, name = _select_flow_interactively()
    if not fid: return
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT point_id, file_name FROM point WHERE flow_id=%s ORDER BY file_name", (fid,))
            pts = cur.fetchall()
            if not pts: return
            print(f"\n{path} 下的文件：")
            for i, (pid, fn) in enumerate(pts,1): print(f"  {i}. {fn}")
            sel = int(input("选择文件编号：").strip())-1
            if sel <0 or sel>=len(pts): return
            pid, fn = pts[sel]
            print("选择目标 Flow：")
            tfid, tpath, tname = _select_flow_interactively()
            if not tfid: return
            cur.execute("SELECT point_id FROM point WHERE file_name=%s AND flow_id=%s", (fn, tfid))
            if cur.fetchone():
                print("目标 Flow 已存在该文件。")
                return
            cur.execute("INSERT INTO point (flow_id, file_name, file_suffix, file_size, file_hash, point_note) SELECT %s, file_name, file_suffix, file_size, file_hash, point_note FROM point WHERE point_id=%s", (tfid, pid))
            conn.commit()
            print(f"已复制到 {tpath}")
    except Exception as e:
        conn.rollback()
        print(f"错误：{e}")
    finally:
        conn.close()

def organizer_menu():
    while True:
        print("\n" + "="*40)
        print("  整理与清理 · 操作中心（可物理删除）")
        print("="*40)
        print(" 1. 删除 point（同时删除物理文件）")
        print(" 2. 删除 Flow（级联删除物理文件）")
        print(" 3. 导出 Flow（递归，保持目录结构）")
        print(" 4. 导出全部 Flow（完整树形）")
        print(" 5. 导出选定 point（按编号复制）")
        print(" 6. 清理悬空 point")
        print(" 0. 返回主菜单")
        ch = input("请选择：").strip()
        if ch == '1':
            delete_point_func()
        elif ch == '2':
            delete_flow_with_files()
        elif ch == '3':
            print("\n--- 递归导出 Flow ---")
            fid, path, name = _select_flow_interactively()
            if fid: export_flow_recursive(fid, path, name)
        elif ch == '4':
            batch_export_all()
        elif ch == '5':
            export_selected_points()
        elif ch == '6':
            clean_dangling_files()
        elif ch == '0':
            break
        else:
            print("无效选择。")
        input("\n按回车键继续...")