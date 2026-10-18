"""
@file main.py
@brief Patho-COT Web 服务启动入口
"""
import uvicorn
import requests

if __name__ == "__main__":
    print("启动 Patho-COT 智能诊断系统 Web 服务...")

    # 检查 Ollama 连通性
    try:
        resp = requests.get("http://localhost:11434/api/tags", timeout=3)
        print("[启动检查] Ollama 服务在线 ✓")
    except Exception as e:
        print(f"[启动检查] Ollama 服务不可达: {e} ⚠")

    print("访问地址: http://127.0.0.1:8001  (局域网设备请使用本机局域网 IP 访问)")
    uvicorn.run("app:app", host="0.0.0.0", port=8001, reload=True)
