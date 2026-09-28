#!/usr/bin/env python
"""
JM 域名连通性测试工具
用法: python test_domain.py
用途: 测试当前网络可以访问哪些禁漫域名，帮助选择最佳域名配置
参考: https://jmcomic.readthedocs.io/zh-cn/latest/tutorial/8_pick_domain/
"""
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
requests.packages.urllib3.disable_warnings()


def test_domain(domain, timeout=10):
    """测试单个域名的可达性和延迟"""
    url = f"https://{domain}/setting"
    try:
        start = time.time()
        r = requests.get(url, timeout=timeout, verify=False,
                        headers={"user-agent": "Mozilla/5.0", "Accept": "*/*"})
        elapsed = (time.time() - start) * 1000
        return {"domain": domain, "status": f"HTTP {r.status_code}", "latency_ms": int(elapsed)}
    except requests.exceptions.Timeout:
        return {"domain": domain, "status": "TIMEOUT", "latency_ms": timeout * 1000}
    except requests.exceptions.ConnectionError as e:
        msg = str(e)[:80]
        if "reset" in msg.lower() or "10054" in msg:
            return {"domain": domain, "status": "RST (被干扰)", "latency_ms": None}
        return {"domain": domain, "status": f"CONN_ERR", "latency_ms": None}
    except Exception as e:
        return {"domain": domain, "status": str(e)[:40], "latency_ms": None}


def get_all_domains():
    """从多个来源收集域名"""
    from jmcomic import JmModuleConfig

    domains = set()

    # 1. 库内置 API 域名
    for d in JmModuleConfig.DOMAIN_API_LIST:
        domains.add(d)

    # 2. 库内置图片 CDN 域名
    for d in JmModuleConfig.DOMAIN_IMAGE_LIST:
        domains.add(d)

    # 3. 尝试从 GitHub 获取最新域名列表
    try:
        html_domains = JmModuleConfig.get_html_domain_all()
        domains.update(html_domains)
    except Exception:
        pass

    # 4. 补充常用域名
    extra = [
        "www.cdnhjk.net", "www.cdngwc.cc", "www.cdngwc.net",
        "www.cdngwc.club", "www.cdnutc.me",
        "18comic.vip", "18comic.org", "jmcomic.me", "jmcomic1.me",
    ]
    for d in extra:
        domains.add(d)

    return sorted(domains)


def main():
    print("=" * 60)
    print("  JM 域名连通性测试")
    print("=" * 60)
    print()

    print("正在收集域名列表...")
    try:
        domains = get_all_domains()
    except Exception as e:
        print(f"收集域名失败: {e}")
        print("使用内置域名列表...")
        from jmcomic import JmModuleConfig
        domains = sorted(set(JmModuleConfig.DOMAIN_API_LIST))

    print(f"共 {len(domains)} 个域名，开始测试...")
    print()

    results = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(test_domain, d): d for d in domains}
        for f in as_completed(futures):
            results.append(f.result())

    # 按状态分组排序
    ok = [r for r in results if r["status"].startswith("HTTP")]
    bad = [r for r in results if r["status"] == "RST (被干扰)"]
    other = [r for r in results if r not in ok and r not in bad]

    print(f"{'域名':<35} {'状态':<18} {'延迟'}")
    print("-" * 65)

    for r in ok:
        print(f"{r['domain']:<35} {r['status']:<18} {r['latency_ms']}ms")
    for r in bad:
        print(f"{r['domain']:<35} {r['status']:<18} -")
    for r in other:
        lat = f"{r['latency_ms']}ms" if r['latency_ms'] else "-"
        print(f"{r['domain']:<35} {r['status']:<18} {lat}")

    print()
    print(f"结果: {len(ok)} 可用, {len(bad)} 被干扰, {len(other)} 其他错误")

    if ok:
        print()
        print("可用域名列表（可写入 option.yml 的 client.domain）:")
        for r in ok:
            print(f"    - {r['domain']}")
    else:
        print()
        print("全部域名不可用！建议:")
        print("  1. 配置代理: 在 option.yml 中设置 client.postman.meta_data.proxies")
        print("  2. 使用代理: proxies: http://127.0.0.1:7890")
        print("  3. 全局 VPN/科学上网")


if __name__ == "__main__":
    main()
