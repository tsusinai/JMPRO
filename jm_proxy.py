"""JMComic HTTP 代理 — 运行在 Windows 本机，通过 GoodbyeDPI 转发请求"""
import socket
import threading
import sys

BIND_HOST = "127.0.0.1"
BIND_PORT = 8888

def handle_client(client_sock, addr):
    try:
        client_sock.settimeout(30)
        data = client_sock.recv(8192)
        if not data:
            client_sock.close()
            return

        first_line = data.split(b"\r\n")[0].decode("utf-8", errors="replace")
        parts = first_line.split()
        if len(parts) < 3 or parts[0] not in ("CONNECT", "GET", "POST", "HEAD"):
            client_sock.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")
            client_sock.close()
            return

        method, target, _ = parts

        if method == "CONNECT":
            # HTTPS: 解析 host:port
            host, port = target.split(":")
            port = int(port)
        else:
            # HTTP: 从 Host header 获取
            headers = {}
            for line in data.split(b"\r\n")[1:]:
                if not line or line == b"":
                    break
                if b":" in line:
                    k, v = line.split(b":", 1)
                    headers[k.decode().lower().strip()] = v.decode().strip()
            target_host = headers.get("host", "")
            if ":" in target_host:
                host, port = target_host.split(":")
                port = int(port)
            else:
                host, port = target_host, 80

        if not host:
            client_sock.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")
            client_sock.close()
            return

        # 连接目标服务器（通过本机 GoodbyeDPI 出网）
        remote_sock = socket.create_connection((host, port), timeout=30)

        if method == "CONNECT":
            client_sock.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        else:
            remote_sock.sendall(data)

        # 双向转发
        def forward(src, dst, name):
            try:
                while True:
                    d = src.recv(65536)
                    if not d:
                        break
                    dst.sendall(d)
            except Exception:
                pass
            finally:
                try:
                    dst.close()
                except Exception:
                    pass

        t1 = threading.Thread(target=forward, args=(client_sock, remote_sock, "c2r"))
        t2 = threading.Thread(target=forward, args=(remote_sock, client_sock, "r2c"))
        t1.daemon = True
        t2.daemon = True
        t1.start()
        t2.start()
        t1.join(timeout=300)
        t2.join(timeout=300)
    except Exception as e:
        pass
    finally:
        try:
            client_sock.close()
        except Exception:
            pass


def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((BIND_HOST, BIND_PORT))
    server.listen(10)
    print(f"[JM Proxy] 监听 {BIND_HOST}:{BIND_PORT} (Ctrl+C 停止)")
    while True:
        try:
            client, addr = server.accept()
            t = threading.Thread(target=handle_client, args=(client, addr))
            t.daemon = True
            t.start()
        except KeyboardInterrupt:
            break
    server.close()


if __name__ == "__main__":
    main()
