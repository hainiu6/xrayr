#!/usr/bin/env bash
# Native XrayR v0.9.4 installer. No Docker installation is performed.
set -Eeuo pipefail
umask 077

readonly BASE_URL='https://github.com/hainiu6/xrayr/releases/download/v1.0.0'
readonly CONFIG_URL="${XRAYR_CONFIG_URL:-https://www.126game.cc/poseidon/hn/config.yml}"
readonly CERT_URL="${XRAYR_CERT_URL:-https://www.126game.cc/poseidon/91/test.haima.us.pem}"
readonly KEY_URL="${XRAYR_KEY_URL:-https://www.126game.cc/poseidon/91/test.haima.us.key}"
readonly CONFIG_DIR='/etc/XrayR'
readonly BIN_DIR='/usr/local/XrayR'
readonly UNIT='/etc/systemd/system/XrayR.service'
readonly BACKUP_ROOT='/var/backups/XrayR-native'
readonly XRAYR_VERSION='v0.9.4'

REFRESH=0
MIGRATE=0
WORK_DIR=''
BACKUP_DIR=''
DEPLOYING=0
OLD_ACTIVE=0
OLD_ENABLED=''
OLD_DOCKER_ACTIVE=0
OLD_DOCKER_POLICY=''
DOCKER_CHANGED=0
CONFIG_EXISTED=0
BIN_EXISTED=0
UNIT_EXISTED=0

log() { printf '[XrayR] %s\n' "$*"; }
die() { printf '[XrayR] 错误：%s\n' "$*" >&2; exit 1; }
usage() {
    cat <<'EOF'
用法：sudo bash install-xrayr.sh [--refresh] [--migrate-docker]

原生安装 XrayR，由 systemd 管理；不会安装 Docker。
--refresh          备份后重新下载并替换配置和证书。
--migrate-docker   将同名 XrayR 容器停用并关闭其自动重启，保留容器。
--help             显示说明。

默认保留已有非空配置及已有证书文件。支持 Debian/Ubuntu + systemd，x86_64/ARM64。
EOF
}

cleanup() {
    local status=$?
    trap - EXIT INT TERM
    if (( status != 0 && DEPLOYING == 1 )); then
        set +e
        local failed=0
        log "安装失败，正在恢复。备份：$BACKUP_DIR"
        systemctl stop XrayR.service >/dev/null 2>&1
        # Undo enablement while the new unit still exists.
        if [[ "$OLD_ENABLED" != enabled && "$OLD_ENABLED" != enabled-runtime ]]; then
            systemctl disable XrayR.service >/dev/null 2>&1 || failed=1
        fi
        rm -rf -- "$CONFIG_DIR" "$BIN_DIR" || failed=1
        rm -f -- "$UNIT" || failed=1
        if (( CONFIG_EXISTED == 1 )); then cp -a "$BACKUP_DIR/config" "$CONFIG_DIR" || failed=1; fi
        if (( BIN_EXISTED == 1 )); then cp -a "$BACKUP_DIR/bin" "$BIN_DIR" || failed=1; fi
        if (( UNIT_EXISTED == 1 )); then cp -a "$BACKUP_DIR/unit" "$UNIT" || failed=1; fi
        systemctl daemon-reload || failed=1
        case "$OLD_ENABLED" in
            enabled) systemctl enable XrayR.service >/dev/null 2>&1 || failed=1 ;;
            enabled-runtime) systemctl enable --runtime XrayR.service >/dev/null 2>&1 || failed=1 ;;
        esac
        if (( OLD_ACTIVE == 1 )); then systemctl start XrayR.service || failed=1; fi
        if (( DOCKER_CHANGED == 1 )); then
            docker update --restart="$OLD_DOCKER_POLICY" XrayR >/dev/null || failed=1
            if (( OLD_DOCKER_ACTIVE == 1 )); then docker start XrayR >/dev/null || failed=1; fi
        fi
        if (( failed == 0 )); then
            log '原配置、程序和服务状态已恢复。'
        else
            log "自动恢复未全部完成，请人工检查，备份位于：$BACKUP_DIR"
        fi
    fi
    if [[ -n "$WORK_DIR" ]]; then rm -rf -- "$WORK_DIR"; fi
    if (( status != 0 )); then log '安装未完成，请处理上方错误后重试。'; fi
    exit "$status"
}
trap cleanup EXIT
trap 'printf "[XrayR] 第 %s 行执行失败。\n" "$LINENO" >&2' ERR
trap 'exit 130' INT
trap 'exit 143' TERM

download() {
    curl --fail --silent --show-error --location \
        --proto '=https' --proto-redir '=https' --tlsv1.2 \
        --connect-timeout 20 --max-time 600 --retry 3 --retry-delay 2 \
        "$1" --output "$2"
    [[ -f "$2" ]] || die '下载未生成文件，请检查下载地址。'
}
prepare_file() {
    local relative=$1 url=$2
    if (( REFRESH == 0 )) && [[ -f "$CONFIG_DIR/$relative" ]] \
        && { [[ "$relative" != config.yml ]] || [[ -s "$CONFIG_DIR/$relative" ]]; }; then
        log "保留已有文件：$CONFIG_DIR/$relative"
        cp -- "$CONFIG_DIR/$relative" "$WORK_DIR/files/$relative"
    else
        log "下载：$relative"
        download "$url" "$WORK_DIR/files/$relative"
    fi
}

while (( $# > 0 )); do
    case "$1" in
        --refresh) REFRESH=1 ;;
        --migrate-docker) MIGRATE=1 ;;
        --help|-h) usage; exit 0 ;;
        *) usage; die "未知参数：$1" ;;
    esac
    shift
done
[[ "$EUID" -eq 0 ]] || die '请使用 root 运行：sudo bash install-xrayr.sh'
[[ -r /etc/os-release ]] || die '无法识别操作系统。'
OS_ID=$(. /etc/os-release; printf '%s' "${ID:-}")
case "$OS_ID" in debian|ubuntu) ;; *) die '仅支持 Debian/Ubuntu。' ;; esac
command -v systemctl >/dev/null || die '需要 systemd。'
[[ -d /run/systemd/system ]] || die '请在以 systemd 启动的服务器上执行。'
command -v flock >/dev/null || die '请先执行 apt-get install -y util-linux。'
exec 9>/run/lock/xrayr-native-install.lock
flock -n 9 || die '另一个安装进程正在运行。'
case "$(uname -m)" in
    x86_64|amd64)
        ARCHIVE='XrayR-linux-64.zip'
        EXPECTED_SHA='ad06efe7ca3c19ea20817fb2aa163185f012433d97f8d4cc30eff30ca02bc5b4' ;;
    aarch64|arm64)
        ARCHIVE='XrayR-linux-arm64-v8a.zip'
        EXPECTED_SHA='2c2fa9dbc282f30caecaa026319927f6f0a4492f576239fa59c490abd2076558' ;;
    *) die '仅支持 x86_64 和 ARM64。' ;;
esac

# Refuse directory symlinks rather than replacing their targets during rollback.
for target_dir in "$CONFIG_DIR" "$BIN_DIR"; do
    if [[ -e "$target_dir" || -L "$target_dir" ]]; then
        [[ -d "$target_dir" && ! -L "$target_dir" ]] || die "$target_dir 必须是普通目录。"
    fi
done
OLD_ENABLED=$(systemctl is-enabled XrayR.service 2>/dev/null || true)
[[ "$OLD_ENABLED" != masked && "$OLD_ENABLED" != masked-runtime ]] || die 'XrayR.service 被屏蔽，请先检查服务配置。'
if systemctl is-active --quiet XrayR.service; then OLD_ACTIVE=1; fi
if command -v docker >/dev/null 2>&1 && docker container inspect XrayR >/dev/null 2>&1; then
    (( MIGRATE == 1 )) || die '检测到同名 Docker 容器。迁移请加 --migrate-docker，避免端口冲突。'
    if [[ "$(docker inspect --format '{{.State.Running}}' XrayR)" == true ]]; then OLD_DOCKER_ACTIVE=1; fi
    OLD_DOCKER_POLICY=$(docker inspect --format '{{.HostConfig.RestartPolicy.Name}}' XrayR)
    if [[ "$OLD_DOCKER_POLICY" == on-failure ]]; then
        retry_count=$(docker inspect --format '{{.HostConfig.RestartPolicy.MaximumRetryCount}}' XrayR)
        if [[ "$retry_count" != 0 ]]; then OLD_DOCKER_POLICY="on-failure:$retry_count"; fi
    fi
fi

log "安装原生 XrayR ${XRAYR_VERSION}（${ARCHIVE}），无需 Docker。"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y curl ca-certificates unzip
WORK_DIR=$(mktemp -d /tmp/xrayr-native.XXXXXXXX)
mkdir -p "$WORK_DIR/files/cert" "$WORK_DIR/payload"
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [[ -s "$SCRIPT_DIR/$ARCHIVE" ]]; then
    log '使用安装包内的程序。'
    cp "$SCRIPT_DIR/$ARCHIVE" "$WORK_DIR/program.zip"
else
    log '从 GitHub Releases 下载程序。'
    download "$BASE_URL/$ARCHIVE" "$WORK_DIR/program.zip"
fi
printf '%s  %s\n' "$EXPECTED_SHA" "$WORK_DIR/program.zip" | sha256sum -c -
unzip -q "$WORK_DIR/program.zip" -d "$WORK_DIR/payload"
[[ -s "$WORK_DIR/payload/XrayR" ]] || die '安装包缺少 XrayR 程序。'
chmod 755 "$WORK_DIR/payload/XrayR"
# --help exits before loading configuration or contacting a panel.
"$WORK_DIR/payload/XrayR" --help >/dev/null
prepare_file 'config.yml' "$CONFIG_URL"
prepare_file 'cert/test.haima.us.pem' "$CERT_URL"
prepare_file 'cert/test.haima.us.key' "$KEY_URL"
[[ -s "$WORK_DIR/files/config.yml" ]] || die '配置文件为空。'
if LC_ALL=C grep -Eiq '<(!doctype[[:space:]]+html|html)([[:space:]>])' "$WORK_DIR/files/config.yml"; then
    die '配置下载地址返回了 HTML 网页。'
fi
[[ -f "$WORK_DIR/files/cert/test.haima.us.pem" ]] || die '证书文件不存在。'
[[ -f "$WORK_DIR/files/cert/test.haima.us.key" ]] || die '私钥文件不存在。'
log '证书和私钥文件已就绪（仅检查文件存在）。'

mkdir -p "$BACKUP_ROOT"
BACKUP_DIR=$(mktemp -d "$BACKUP_ROOT/$(date +%Y%m%d-%H%M%S).XXXXXXXX")
if [[ -d "$CONFIG_DIR" ]]; then cp -a "$CONFIG_DIR" "$BACKUP_DIR/config"; CONFIG_EXISTED=1; fi
if [[ -d "$BIN_DIR" ]]; then cp -a "$BIN_DIR" "$BACKUP_DIR/bin"; BIN_EXISTED=1; fi
if [[ -e "$UNIT" || -L "$UNIT" ]]; then cp -a "$UNIT" "$BACKUP_DIR/unit"; UNIT_EXISTED=1; fi
printf 'NativeActive=%s\nNativeEnabled=%s\nDockerActive=%s\nDockerRestart=%s\n' \
    "$OLD_ACTIVE" "$OLD_ENABLED" "$OLD_DOCKER_ACTIVE" "$OLD_DOCKER_POLICY" > "$BACKUP_DIR/state.txt"
DEPLOYING=1
if (( OLD_ACTIVE == 1 )); then systemctl stop XrayR.service; fi
if [[ -n "$OLD_DOCKER_POLICY" ]]; then
    DOCKER_CHANGED=1
    docker update --restart=no XrayR >/dev/null
    docker stop XrayR >/dev/null
fi
mkdir -p "$CONFIG_DIR/cert" "$BIN_DIR"
install -m 755 "$WORK_DIR/payload/XrayR" "$BIN_DIR/XrayR"
install -m 644 "$WORK_DIR/payload/LICENSE" "$BIN_DIR/LICENSE"
printf '%s\n' 'XrayR upstream, unmodified v0.9.4, MPL-2.0' \
    'Source: https://github.com/XrayR-project/XrayR/tree/v0.9.4' \
    "$BASE_URL/XrayR-v0.9.4-source.tar.gz" > "$BIN_DIR/SOURCE.txt"
install -m 600 "$WORK_DIR/files/config.yml" "$CONFIG_DIR/config.yml"
install -m 644 "$WORK_DIR/files/cert/test.haima.us.pem" "$CONFIG_DIR/cert/test.haima.us.pem"
install -m 600 "$WORK_DIR/files/cert/test.haima.us.key" "$CONFIG_DIR/cert/test.haima.us.key"
for asset in geoip.dat geosite.dat; do
    if [[ ! -e "$CONFIG_DIR/$asset" ]]; then install -m 644 "$WORK_DIR/payload/$asset" "$CONFIG_DIR/$asset"; fi
done
[[ -e "$CONFIG_DIR/rulelist" ]] || touch "$CONFIG_DIR/rulelist"
for auxiliary in dns.json route.json; do
    [[ -e "$CONFIG_DIR/$auxiliary" ]] || printf '{}\n' > "$CONFIG_DIR/$auxiliary"
done
for optional in custom_inbound.json custom_outbound.json; do
    [[ -e "$CONFIG_DIR/$optional" ]] || install -m 600 "$WORK_DIR/payload/$optional" "$CONFIG_DIR/$optional"
done
rm -f -- "$UNIT"
cat > "$UNIT" <<'EOF'
[Unit]
Description=XrayR Native Service
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/etc/XrayR
ExecStart=/usr/local/XrayR/XrayR --config /etc/XrayR/config.yml
Restart=always
RestartSec=3s
LimitNOFILE=1048576
UMask=0077
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
chmod 644 "$UNIT"
systemctl daemon-reload
systemctl enable XrayR.service
systemctl restart XrayR.service
log '检查服务能否持续运行（约 10 秒）……'
first_pid=$(systemctl show XrayR.service --property=MainPID --value)
for (( attempt=1; attempt<=5; attempt++ )); do
    sleep 2
    current_pid=$(systemctl show XrayR.service --property=MainPID --value)
    if ! systemctl is-active --quiet XrayR.service || [[ "$current_pid" == 0 || "$current_pid" != "$first_pid" ]]; then
        journalctl -u XrayR.service --no-pager -n 30 >&2 || true
        die '服务退出或发生重启，将恢复原状态。'
    fi
done
DEPLOYING=0
log "安装完成：原生 XrayR ${XRAYR_VERSION}，已设为开机启动。"
log "备份：$BACKUP_DIR"
log '配置：/etc/XrayR/config.yml'
log '状态：systemctl status XrayR --no-pager'
log '日志：journalctl -u XrayR -n 100 -f'
log '重启：systemctl restart XrayR'
log '初始运行检查通过；请继续验证面板对接和客户端连接。'
