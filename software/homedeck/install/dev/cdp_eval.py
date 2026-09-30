import base64, json, os, socket, struct, sys, urllib.request, urllib.parse
expr = sys.argv[1]
tabs = json.load(urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=3))
page = next(t for t in tabs if t.get("type") == "page")
u = urllib.parse.urlparse(page["webSocketDebuggerUrl"])
sk = socket.create_connection((u.hostname, u.port), timeout=5)
key = base64.b64encode(os.urandom(16)).decode()
sk.sendall((f"GET {u.path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\nOrigin: http://127.0.0.1:9222\r\n\r\n").encode())
buf = b""
while b"\r\n\r\n" not in buf: buf += sk.recv(4096)
assert b" 101 " in buf.split(b"\r\n")[0], buf[:80]
payload = json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": expr, "returnByValue": True}}).encode()
mask = os.urandom(4); hdr = bytes([0x81])
n = len(payload)
hdr += bytes([0x80 | n]) if n < 126 else bytes([0x80 | 126]) + struct.pack(">H", n)
sk.sendall(hdr + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))
data = buf.split(b"\r\n\r\n", 1)[1]
while True:
    data += sk.recv(65536)
    if len(data) < 2: continue
    ln = data[1] & 0x7f; off = 2
    if ln == 126: ln = struct.unpack(">H", data[2:4])[0]; off = 4
    elif ln == 127: ln = struct.unpack(">Q", data[2:10])[0]; off = 10
    if len(data) >= off + ln:
        print(data[off:off + ln].decode(errors="replace")[:300]); break
