import pymysql
import traceback
from .database import get_conn, get_root_id


def _get_flow_path(cur, flow_id, flows_cache):
    """根据 flow_id 返回完整路径字符串（已修复缓存缺失问题）"""
    parts = []
    current_id = flow_id
    
    while current_id is not None:
        # 缓存缺失时自动从数据库查询并更新缓存
        if current_id not in flows_cache:
            cur.execute("SELECT flow_name, parent_flow_id FROM flow WHERE flow_id=%s", (current_id,))
            row = cur.fetchone()
            if not row:
                raise Exception(f"Flow ID {current_id} 在数据库中不存在")
            flows_cache[current_id] = {"name": row[0], "parent": row[1]}
        
        parts.append(flows_cache[current_id]["name"])
        current_id = flows_cache[current_id]["parent"]
    
    return "/" + "/".join(reversed(parts))


def show_tree():
    """以树形结构显示所有 Flow 及其文件数量"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # 一次性加载所有 Flow 数据
            cur.execute("SELECT flow_id, flow_name, parent_flow_id FROM flow ORDER BY parent_flow_id, flow_name")
            flows = {row[0]: {"name": row[1], "parent": row[2]} for row in cur.fetchall()}
            
            # 一次性加载所有文件数量统计
            cur.execute("SELECT flow_id, COUNT(*) FROM point GROUP BY flow_id")
            point_counts = {row[0]: row[1] for row in cur.fetchall()}

            # 可选：颜色支持
            try:
                from colorama import init, Fore, Style
                init(autoreset=True)
                COLOR_FILE = Fore.GREEN
                use_color = True
            except ImportError:
                use_color = False

            def get_children(parent_id):
                return sorted([k for k, v in flows.items() if v["parent"] == parent_id])

            def print_node(node_id, prefix="", is_last=True):
                node = flows[node_id]
                cnt = point_counts.get(node_id, 0)
                connector = "└── " if is_last else "├── "
                
                if use_color and cnt > 0:
                    label = f"{COLOR_FILE}[{node['name']}] ({cnt} 文件)"
                else:
                    label = f"[{node['name']}] ({cnt} 文件)"
                
                print(prefix + connector + label)

                children = get_children(node_id)
                for i, child in enumerate(children):
                    is_last_child = (i == len(children) - 1)
                    new_prefix = prefix + ("    " if is_last else "│   ")
                    print_node(child, new_prefix, is_last_child)

            # 打印根节点
            root_id = get_root_id(cur)
            root_cnt = point_counts.get(root_id, 0)
            
            if use_color and root_cnt > 0:
                root_label = f"{COLOR_FILE}[ROOT] ({root_cnt} 文件)"
            else:
                root_label = f"[ROOT] ({root_cnt} 文件)"
            
            print(root_label)
            
            # 打印子节点
            children = get_children(root_id)
            for i, child in enumerate(children):
                print_node(child, "", i == len(children) - 1)

    except Exception as e:
        print(f"[错误] 无法显示树: {type(e).__name__}: {e}")
        traceback.print_exc()
    finally:
        conn.close()


def get_flow_by_path(cur, path_str):
    """根据路径获取 Flow ID，不存在则自动创建（已优化异常处理）"""
    parts = [p.strip() for p in path_str.strip().split("/") if p.strip()]
    
    if not parts or parts[0] != "ROOT":
        raise ValueError("路径必须以 /ROOT 开头")
    
    parent_id = get_root_id(cur)
    
    for part in parts[1:]:
        # 先查询是否已存在
        cur.execute("SELECT flow_id FROM flow WHERE flow_name=%s AND parent_flow_id=%s", (part, parent_id))
        row = cur.fetchone()
        
        if row:
            parent_id = row[0]
            continue
        
        # 不存在则尝试创建
        try:
            cur.execute("SET FOREIGN_KEY_CHECKS=0")
            cur.execute("INSERT INTO flow (flow_name, parent_flow_id) VALUES (%s, %s)", (part, parent_id))
            cur.execute("SET FOREIGN_KEY_CHECKS=1")
            print(f"[自动创建 Flow] {part}")
        except Exception as e:
            # 确保无论如何都恢复外键检查
            try:
                cur.execute("SET FOREIGN_KEY_CHECKS=1")
            except Exception as inner_e:
                print(f"[警告] 恢复外键检查失败: {inner_e}")
            print(f"[警告] 创建 Flow {part} 时发生异常: {e}")
        
        # 再次查询确认
        cur.execute("SELECT flow_id FROM flow WHERE flow_name=%s AND parent_flow_id=%s", (part, parent_id))
        row = cur.fetchone()
        
        if not row:
            raise Exception(f"无法创建或找到 Flow：{part} (父ID: {parent_id})")
        
        parent_id = row[0]
    
    return parent_id


def create_flow():
    """交互式创建 Flow（已修复缓存不更新导致的路径获取错误）"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # 初始加载所有 Flow 到缓存
            cur.execute("SELECT flow_id, flow_name, parent_flow_id FROM flow ORDER BY parent_flow_id, flow_name")
            all_flows = {row[0]: {"name": row[1], "parent": row[2]} for row in cur.fetchall()}
            
            current_id = get_root_id(cur)

            while True:
                # 从缓存获取当前 Flow 信息（避免重复查询数据库）
                current_flow = all_flows[current_id]
                cur.execute("SELECT COUNT(*) FROM point WHERE flow_id=%s", (current_id,))
                file_cnt = cur.fetchone()[0]
                
                print(f"\n当前 Flow: {current_flow['name']}  ({file_cnt} 文件)")

                # 获取子 Flow 列表
                cur.execute("SELECT flow_id, flow_name FROM flow WHERE parent_flow_id=%s ORDER BY flow_name", (current_id,))
                children = cur.fetchall()

                # 打印菜单
                if children:
                    print("子 Flow：")
                    print("  0. [在此 Flow 下创建新子 Flow]")
                    for i, child in enumerate(children, start=1):
                        print(f"  {i}. {child[1]}")
                    print("  b. 返回上级  q. 退出")
                else:
                    print("（没有子 Flow）")
                    print("  0. 在此 Flow 下创建新子 Flow")
                    print("  b. 返回上级  q. 退出")

                # 处理用户输入
                choice = input("请选择：").strip().lower()
                
                if choice == "0":
                    # 创建新 Flow
                    new_name = input("输入新 Flow 名称：").strip()
                    
                    if not new_name:
                        print("错误：名称不能为空。")
                        continue

                    # 检查重名
                    cur.execute("SELECT flow_id FROM flow WHERE flow_name=%s AND parent_flow_id=%s", (new_name, current_id))
                    if cur.fetchone():
                        print(f"错误：当前目录下已存在名为 '{new_name}' 的 Flow。")
                        continue

                    # 执行插入
                    try:
                        cur.execute("SET FOREIGN_KEY_CHECKS=0")
                        cur.execute("INSERT INTO flow (flow_name, parent_flow_id) VALUES (%s, %s)", (new_name, current_id))
                        cur.execute("SET FOREIGN_KEY_CHECKS=1")
                        conn.commit()
                    except Exception as e:
                        conn.rollback()
                        # 确保恢复外键检查
                        try:
                            cur.execute("SET FOREIGN_KEY_CHECKS=1")
                        except Exception as inner_e:
                            print(f"[警告] 恢复外键检查失败: {inner_e}")
                        print(f"错误：创建失败 - {e}")
                        continue

                    # 查询新创建的 Flow ID
                    cur.execute("SELECT flow_id FROM flow WHERE flow_name=%s AND parent_flow_id=%s", (new_name, current_id))
                    result = cur.fetchone()
                    
                    if result:
                        new_id = result[0]
                        # --------------------------
                        # 核心修复：更新 all_flows 缓存
                        # --------------------------
                        all_flows[new_id] = {"name": new_name, "parent": current_id}
                        # 获取完整路径
                        path = _get_flow_path(cur, new_id, all_flows)
                        print(f"✅ Flow 创建成功！路径：{path}")
                    else:
                        print("❌ 创建失败：数据库未返回新创建的 Flow ID，请检查数据库状态。")
                    break
                
                elif choice == "b":
                    # 返回上级
                    parent_id = all_flows[current_id]["parent"]
                    if parent_id is None:
                        print("已在根目录，无法返回上级。")
                    else:
                        current_id = parent_id
                
                elif choice == "q":
                    print("已取消创建。")
                    break
                
                else:
                    # 选择子 Flow
                    try:
                        idx = int(choice) - 1
                        if 0 <= idx < len(children):
                            current_id = children[idx][0]
                        else:
                            print("错误：无效的数字选项。")
                    except ValueError:
                        print("错误：无效输入，请输入数字、b 或 q。")
    
    except Exception as e:
        conn.rollback()
        print(f"\n❌ 发生未捕获的错误：")
        print(f"错误类型：{type(e).__name__}")
        print(f"错误信息：{e}")
        print("详细堆栈跟踪：")
        traceback.print_exc()
    
    finally:
        conn.close()


def get_subflow_ids(cur, parent_id):
    """递归获取指定 Flow 及其所有子 Flow 的 ID 列表（已优化性能）"""
    ids = [parent_id]
    
    # 使用参数化查询，避免 SQL 注入
    cur.execute("SELECT flow_id FROM flow WHERE parent_flow_id=%s", (parent_id,))
    
    for row in cur.fetchall():
        child_id = row[0]
        ids.extend(get_subflow_ids(cur, child_id))
    
    return ids