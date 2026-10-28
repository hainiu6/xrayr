# XrayR 原生一键安装

无需 Docker，直接安装官方 XrayR v0.9.4 二进制，使用 systemd 管理服务。

- 系统：Debian / Ubuntu，需使用 systemd。
- 架构：x86_64 / ARM64 自动识别。
- 安装：以 root 运行，需要联网下载程序、配置、证书和缺少的 apt 依赖。
- 重装：备份旧文件，默认保留已有非空配置和已有证书文件。
- 证书：仅检查证书、私钥文件存在，不验证格式、有效期或是否匹配。
- 保护：程序包 SHA-256 校验、服务启动检查、失败自动恢复。

## 一键安装

```bash
wget -O /tmp/install-xrayr.sh https://raw.githubusercontent.com/hainiu6/xrayr/main/install-xrayr.sh && bash /tmp/install-xrayr.sh
```

也可以使用 curl：

```bash
curl -fL https://raw.githubusercontent.com/hainiu6/xrayr/main/install-xrayr.sh -o /tmp/install-xrayr.sh && bash /tmp/install-xrayr.sh
```

脚本及程序包从 GitHub 获取。发布下载：
<https://github.com/hainiu6/xrayr/releases/latest>。

## 完整安装包

Release 中的 `xrayr-native-installer.tar.gz` 包含安装脚本、x86_64/ARM64 两种程序包、源码和许可说明。

```bash
wget -O xrayr-native-installer.tar.gz https://github.com/hainiu6/xrayr/releases/download/v1.0.0/xrayr-native-installer.tar.gz
tar -xzf xrayr-native-installer.tar.gz
cd xrayr-native-installer
bash install-xrayr.sh
```

脚本优先使用同目录中的程序包。系统依赖、配置和证书下载仍需要联网。

## 配置和证书

本公开仓库不包含实际面板 ApiKey、运行配置或证书私钥。默认仍从原地址获取这些文件：

```text
https://www.126game.cc/poseidon/hn/config.yml
https://www.126game.cc/poseidon/91/test.haima.us.pem
https://www.126game.cc/poseidon/91/test.haima.us.key
```

安装脚本、二进制程序和完整包的下载已迁移到 GitHub。实际配置和私钥的迁移需要另行确定公开方式。

配置位置：`/etc/XrayR/config.yml`。

证书位置：

```text
/etc/XrayR/cert/test.haima.us.pem
/etc/XrayR/cert/test.haima.us.key
```

可通过环境变量指定自己的下载地址：

```bash
XRAYR_CONFIG_URL='https://example.com/config.yml' \
XRAYR_CERT_URL='https://example.com/server.pem' \
XRAYR_KEY_URL='https://example.com/server.key' \
bash /tmp/install-xrayr.sh
```

下载配置中的证书路径必须与实际安装位置一致。安装器不会改写面板地址、ApiKey、节点 ID、协议或端口。

证书和私钥文件存在即可继续安装。文件实际不可用时，XrayR 启动或客户端连接仍可能失败。
下载请求仍会校验 HTTPS，程序包仍会核对固定 SHA-256。

## 日常管理

```bash
# 启动
systemctl start XrayR

# 重启，修改配置后使用
systemctl restart XrayR

# 停止
systemctl stop XrayR

# 状态
systemctl status XrayR --no-pager

# 实时日志；Ctrl+C 退出不会停止服务
journalctl -u XrayR -n 100 -f

# 开机自启
systemctl enable XrayR

# 取消开机自启
systemctl disable XrayR
```

## 重装、刷新和容器迁移

普通重装保留配置和证书。重新下载并替换配置、证书和私钥：

```bash
bash /tmp/install-xrayr.sh --refresh
```

已存在名为 `XrayR` 的 Docker 容器时，迁移到原生服务：

```bash
bash /tmp/install-xrayr.sh --migrate-docker
```

迁移会停止该容器并关闭其自动重启，保留容器、Docker 和其他容器。
新服务初始运行检查失败时，安装器会尝试恢复原配置、程序、服务状态及旧容器的重启策略。
不会自动处理其他名称的容器、不同服务名或手工启动的进程。

## 文件位置

| 内容 | 路径 |
| --- | --- |
| 程序 | `/usr/local/XrayR/XrayR` |
| 配置和地理数据库 | `/etc/XrayR/` |
| systemd 服务 | `/etc/systemd/system/XrayR.service` |
| 安装前备份 | `/var/backups/XrayR-native/时间戳.随机后缀/` |

首次创建的 `rulelist` 为空，`dns.json`、`route.json` 为 `{}`。已有辅助文件和地理数据库保留。
配置与私钥权限为 600。证书直接放入 cert 目录，不在 `/root` 额外保存副本。

安装完成后检查服务连续运行约 10 秒且主进程未重启。还需自行验证面板对接与客户端连接。

## 开发和发布

```bash
bash -n install-xrayr.sh
python3 qa/test_install.py
python3 tools/build_release.py
```

测试使用临时目录和替身命令，不修改本机服务。
发布构建会核对上游摘要、ZIP 完整性及 ELF 架构，并在 Linux x86_64 上使用真实程序检查 `--config` 参数。
提交到 main 后，GitHub Actions 会完成测试、构建、发布和下载校验。
发布新版本需同步更新 `VERSION` 和安装脚本内的 Release 地址，已发布版本不会移动到另一个提交。

本安装器版本 v1.0.0，上游核心版本 v0.9.4。来源及 MPL-2.0 许可说明见 [NOTICE.md](NOTICE.md) 和 [LICENSE](LICENSE)。
