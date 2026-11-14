"""诊断：反复开关服务后，Windows 音频端点是否还能出现。"""
import subprocess
import sys
import time

sys.path.insert(0, ".")
from oppo import btwin

A = "00:A4:1C:2A:D5:A7"
A2DP = "{0000110B-0000-1000-8000-00805F9B34FB}"


def endpoints() -> str:
    ps = ("Get-PnpDevice -Class AudioEndpoint | "
          "Where-Object { $_.FriendlyName -like '*Free4*' } | "
          "ForEach-Object { $_.Status + ' | ' + $_.FriendlyName }")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                         capture_output=True, text=True, timeout=30)
    return (out.stdout or "").strip() or "(无音频端点)"


def set_svc(guid: str, state: int):
    def run(lib, hradio):
        info = btwin._device_info(lib, hradio, A)
        t = time.time()
        r = btwin._set_service(lib, hradio, info, guid, state)
        return r, round(time.time() - t, 2)
    return btwin._with_radio(run)


if __name__ == "__main__":
    print("初始端点:", endpoints())
    print("链路:", btwin.is_connected(A))
    print("\n[1] 只 enable A2DP ->", set_svc(A2DP, 1))
    for i in range(6):
        time.sleep(1)
        print(f"  {i + 1}s 端点:", endpoints())
