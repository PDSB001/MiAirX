"""MiAirX 一键启动脚本"""

import os
import sys
import subprocess

# 设置工作目录
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# 设置 PYTHONPATH
os.environ["PYTHONPATH"] = "src"

print("=" * 60)
print("MiAirX - 小米音箱 DLNA/AirPlay 桥接器")
print("=" * 60)

# 检查配置文件
config_file = "conf/config.json"
if not os.path.exists(config_file):
    print("\n[提示] 配置文件不存在，正在创建...")
    os.makedirs("conf", exist_ok=True)
    
    # 复制示例配置
    if os.path.exists("config-example.json"):
        import shutil
        shutil.copy("config-example.json", config_file)
        print(f"[完成] 已创建配置文件: {config_file}")
        print("[提示] 请编辑配置文件，填入你的小米账号信息")
    else:
        # 创建默认配置
        import json
        default_config = {
            "account": "",
            "password": "",
            "mi_did": "",
            "hostname": "",
            "dlna_port": 8200,
            "web_port": 8300,
            "conf_path": "conf",
            "verbose": False,
            "default_volume": 50,
        }
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(default_config, f, indent=2, ensure_ascii=False)
        print(f"[完成] 已创建默认配置文件: {config_file}")

# 显示配置信息
print("\n[配置信息]")
print(f"  配置文件: {config_file}")
print(f"  DLNA 端口: 8200")
print(f"  Web 端口: 8300")
print(f"  Web 界面: http://localhost:8300")

print("\n[启动服务]")
print("  按 Ctrl+C 停止服务")
print("-" * 60)

# 启动服务
try:
    subprocess.run([sys.executable, "-m", "miairx"], check=True)
except KeyboardInterrupt:
    print("\n\n[停止] 服务已停止")
except Exception as e:
    print(f"\n[错误] 启动失败: {e}")
    sys.exit(1)
