#!/bin/bash
# 自动检查并更新 Let's Encrypt SSL 证书
# Author: Yanyi Cao
# Date: 2025-11-07

CONFIG_FILE="domains.conf"
LOG_FILE="/var/log/ssl_renew.log"
CERTBOT_BIN="/usr/bin/certbot"  # Certbot执行路径
CERTS_DIR="/etc/certs" # 证书存储目录，证书路径为 $CERTS_DIR/$DOMAIN/fullchain.pem，如果配置文件中有配置路径，则使用配置文件的路径
DEFAULT_EMAIL="admin@example.com" # 申请证书时的邮箱
RELOAD_CMD="systemctl reload nginx" # 证书安装成功后执行的命令

# 检查配置文件是否存在
if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "$(date '+%F %T') [ERROR] 配置文件不存在: $CONFIG_FILE" | tee -a "$LOG_FILE"
    exit 1
fi

if [[ ! -f $CERTBOT_BIN ]]; then
    echo "$(date '+%F %T') [ERROR] 未找到 certbot 执行文件: $CERTBOT_BIN，正在尝试安装..." | tee -a "$LOG_FILE"
    if [[ -f /etc/redhat-release ]]; then
        ym update
        yum install certbot -y
    elif [[ -f /etc/lsb-release ]]; then
        apt-get update
        apt-get install certbot -y
    fi

    CERTBOT_BIN=$(which certbot)
    if [[ -z $CERTBOT_BIN || ! -f $CERTBOT_BIN ]]; then
        echo "$(date '+%F %T') [ERROR] 未找到 certbot 执行文件: $CERTBOT_BIN，如未安装，请参考 https://letsencrypt.org/getting-started/" | tee -a "$LOG_FILE"
        exit 1
    fi
fi

echo "$(date '+%F %T') [INFO] 开始检查证书更新任务..." | tee -a "$LOG_FILE"

# 解析配置文件
while read -r line; do
    # 跳过空行或注释
    [[ -z "$line" || "$line" =~ ^# ]] && continue

    key=$(echo $line | cut -d'=' -f1)
    value=$(echo $line | cut -d'=' -f2-)

    # 处理变量
    case $key in
        domain) DOMAIN=$value ;;
        webroot) WEBROOT=$value ;;
        email) EMAIL=$value ;;
        cert_dir) SAVE_CERT_DIR=$value ;;
    esac

    # 当三个变量都有值时执行证书检查
    if [[ -n "$DOMAIN" && -n "$WEBROOT" && -n "$EMAIL" ]]; then
        CERT_PATH="$SAVE_CERT_DIR/fullchain.pem"
        NEED_RENEW=false

        if [[ -f "$CERT_PATH" ]]; then
            # 检查证书到期时间
            EXPIRY_DATE=$(openssl x509 -enddate -noout -in "$CERT_PATH" | cut -d= -f2)
            EXPIRY_TIMESTAMP=$(date -d "$EXPIRY_DATE" +%s)
            NOW_TIMESTAMP=$(date +%s)
            REMAIN_DAYS=$(( ($EXPIRY_TIMESTAMP - $NOW_TIMESTAMP) / 86400 ))

            if (( REMAIN_DAYS <= 1 )); then
                NEED_RENEW=true
                echo "$(date '+%F %T') [INFO] 域名 $DOMAIN 证书将于 $REMAIN_DAYS 天后到期，准备续期..." | tee -a "$LOG_FILE"
            else
                echo "$(date '+%F %T') [INFO] 域名 $DOMAIN 证书仍有 $REMAIN_DAYS 天有效期，无需更新。" | tee -a "$LOG_FILE"
            fi
        else
            NEED_RENEW=true
            echo "$(date '+%F %T') [INFO] 域名 $DOMAIN 尚未存在证书，开始申请新证书..." | tee -a "$LOG_FILE"
        fi

        if [[ "$NEED_RENEW" == true ]]; then
            $CERTBOT_BIN certonly \
                --webroot -w "$WEBROOT" \
                -d "$DOMAIN" \
                -m "$EMAIL" \
                --agree-tos \
                --non-interactive \
                --quiet
            if [[ $? -eq 0 ]]; then
                cp -rf "/etc/letsencrypt/live/$DOMAIN" "$SAVE_CERT_DIR"
                rm -rf "/etc/letsencrypt/live/$DOMAIN"

                $RELOAD_CMD
                echo "$(date '+%F %T') [INFO] 域名 $DOMAIN 证书申请/续期成功。" | tee -a "$LOG_FILE"
            else
                echo "$(date '+%F %T') [ERROR] 域名 $DOMAIN 证书申请/续期失败。" | tee -a "$LOG_FILE"
            fi
        fi

        # 重置变量
        DOMAIN=""
        WEBROOT=""
        EMAIL="$DEFAULT_EMAIL"
        SAVE_CERT_DIR="$CERTS_DIR/$DOMAIN"
    fi
done < "$CONFIG_FILE"

echo "$(date '+%F %T') [INFO] 证书检查任务结束。" | tee -a "$LOG_FILE"
