import requests, os

# 1. 变量检测
feishu_url = os.getenv("FEISHU_WEBHOOK")
ali_key = os.getenv("DASHSCOPE_API_KEY")

print("--- [Step 1: 环境审计] ---")
print(f"飞书 Webhook 状态: {'✅ 已加载' if feishu_url else '❌ 未读取 (检查 GitHub Secrets)'}")
print(f"阿里 API Key 状态: {'✅ 已加载' if ali_key else '❌ 未读取 (检查 GitHub Secrets)'}")

if not feishu_url or not ali_key:
    exit("🛑 环境变量缺失，请先在 GitHub Settings 中检查变量名。")

# 2. 飞书通信测试
print("\n--- [Step 2: 飞书通道审计] ---")
test_card = {
    "msg_type": "text",
    "content": {"text": "🚨 CIO 链路自检：飞书通道正常 ✅"}
}
try:
    fs_res = requests.post(feishu_url, json=test_card, timeout=10)
    if fs_res.status_code == 200:
        print("✅ 飞书测试消息已发出，请检查手机。")
    else:
        print(f"❌ 飞书报错: {fs_res.status_code} - {fs_res.text}")
except Exception as e:
    print(f"❌ 飞书连接失败: {str(e)}")

# 3. 阿里百炼 API 测试
print("\n--- [Step 3: 阿里百炼权限审计] ---")
headers = {"Authorization": f"Bearer {ali_key}", "Content-Type": "application/json"}
payload = {
    "model": "qwen-max",
    "input": {"messages": [{"role": "user", "content": "ping"}]},
    "parameters": {"result_format": "message"}
}
try:
    ali_res = requests.post(
        "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
        headers=headers, json=payload, timeout=15
    )
    if ali_res.status_code == 200:
        print("✅ 阿里百炼 API 调用成功，免费额度正常抵扣。")
    else:
        print(f"❌ 阿里报错: {ali_res.status_code} - {ali_res.text}")
except Exception as e:
    print(f"❌ 阿里连接失败: {str(e)}")
