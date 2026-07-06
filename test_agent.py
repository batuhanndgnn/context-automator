# Manuel smoke-test script'i (pytest değil). resolve_git_state burada
# context_name VERMEDEN çağrılıyor — bu, sunucunun _current_project_dir'e
# (yoksa Path.cwd()'e) düşmesini test eder. Önceden burada hardcoded bir
# kişisel path'e ("C:\Users\bdogan\Desktop\context-automator-clean") düşülüyordu,
# bu bug düzeltildi (bkz. mcp_server.py: resolve_git_state).
import json
import subprocess

cmd = [r".\.venv\Scripts\python.exe", "-m", "context_automator.mcp_server"]
process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)

# 1. Initialize
init_msg = json.dumps({
    "jsonrpc": "2.0",
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05", 
        "capabilities": {},
        "clientInfo": {"name": "test-harness", "version": "1.0"}
    },
    "id": 0
})
process.stdin.write(init_msg + "\n")
process.stdin.flush()
print("Sunucu Yanıtı:", process.stdout.readline().strip())

# 2. Tool Çağrısı (commit_wip)
git_test = json.dumps({
    "jsonrpc": "2.0", 
    "method": "tools/call", 
    "params": {
        "name": "resolve_git_state", 
        "arguments": {"action": "commit_wip"}
    }, 
    "id": 1
})
process.stdin.write(git_test + "\n")
process.stdin.flush()

print("Git işlemi başlatıldı, sunucunun yanıtı bekleniyor (Bu işlem arka planda 10-15 saniye sürebilir)...")

# readline() komutu sunucudan cevap gelene kadar sistemi açık tutar (fişi çekmez)
print("Tool Yanıtı:", process.stdout.readline().strip())
process.terminate()