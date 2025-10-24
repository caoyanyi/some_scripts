#!/bin/bash

# 邮件系统部署脚本

# 配置参数
DOMAIN=""
ADMIN_EMAIL=""
ADMIN_PASSWORD=""

# 函数：显示帮助信息
show_help() {
    echo "用法: $0 --domain <域名> --email <管理员邮箱> --password <管理员密码>"
    echo ""
    echo "选项:"
    echo "  --domain    设置邮件服务器域名"
    echo "  --email     设置管理员邮箱地址"
    echo "  --password  设置管理员邮箱密码"
    echo "  --help      显示此帮助信息"
    echo "  --add-user  添加新用户（格式: 邮箱地址）"
    echo "  --user-password 添加用户的密码"
}

# 解析命令行参数
parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --domain)
                DOMAIN="$2"
                shift 2
                ;;
            --email)
                ADMIN_EMAIL="$2"
                shift 2
                ;;
            --password)
                ADMIN_PASSWORD="$2"
                shift 2
                ;;
            --help)
                show_help
                exit 0
                ;;
            --add-user)
                ADD_USER="$2"
                shift 2
                ;;
            --user-password)
                USER_PASSWORD="$2"
                shift 2
                ;;
            *)
                echo "未知选项: $1"
                show_help
                exit 1
                ;;
        esac
    done

    # 检查必要参数
    if [[ -z "$DOMAIN" || -z "$ADMIN_EMAIL" || -z "$ADMIN_PASSWORD" ]]; then
        echo "错误: 缺少必要参数"
        show_help
        exit 1
    fi
}

# 函数：安装必要的软件包
install_packages() {
    echo "正在安装必要的软件包..."
    apt update
    apt install -y postfix dovecot-core dovecot-imapd dovecot-pop3d dovecot-lmtpd ssl-cert ufw

    # 移除所有snakeoil证书相关代码
    # 生成包含域名的自签名SSL证书（仅生成一次）
    local cert_path="/etc/ssl/certs/mail-$DOMAIN-cert.pem"
    local key_path="/etc/ssl/private/mail-$DOMAIN-key.pem"

    # 如果证书不存在则生成
    if [ ! -f "$cert_path" ] || [ ! -f "$key_path" ]; then
        echo "生成域名特定SSL证书: $cert_path"
        if ! openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout "$key_path" -out "$cert_path" -subj "/CN=$DOMAIN" 2>&1; then
            echo "错误：域名特定SSL证书生成失败，请检查openssl是否正确安装及权限是否足够"
            exit 1
        fi
    else
        echo "域名特定SSL证书已存在，跳过生成"
    fi

    # 验证证书文件存在且非空
    if [ ! -f "$cert_path" ] || [ ! -s "$cert_path" ]; then
        echo "错误：域名特定SSL证书文件不存在或为空"
        echo "证书路径: $cert_path"
        exit 1
    fi

    if [ ! -f "$key_path" ] || [ ! -s "$key_path" ]; then
        echo "错误：域名特定SSL密钥文件不存在或为空"
        echo "密钥路径: $key_path"
        exit 1
    fi

    # 验证证书主题与域名匹配
    echo "正在验证证书主题: $cert_path"
    CERT_SUBJECT=$(openssl x509 -in "$cert_path" -noout -subject -nameopt RFC2253 2>&1)
    if [ $? -ne 0 ]; then
        echo "错误：提取证书主题失败，openssl输出: $CERT_SUBJECT"
        exit 1
    fi
    if [ -z "$CERT_SUBJECT" ]; then
        echo "错误：提取的证书主题为空，请检查证书文件是否有效"
        exit 1
    fi
    echo "证书主题提取结果: $CERT_SUBJECT"
    if [[ ! "$CERT_SUBJECT" =~ CN[[:space:]]*=[[:space:]]*$DOMAIN(,|$) ]]; then
        echo "错误：SSL证书主题与域名不匹配"
        echo "预期域名: $DOMAIN"
        echo "实际主题: $CERT_SUBJECT"
        exit 1
    fi

    # 设置证书和密钥权限
    chmod 644 "$cert_path"
    chmod 640 "$key_path"
    chgrp ssl-cert "$key_path"
    # 添加dovecot用户到ssl-cert组以访问私钥
    usermod -aG ssl-cert dovecot
}

# 函数：配置Postfix
configure_postfix() {
    echo "正在配置Postfix..."
    # 备份原始配置
    cp /etc/postfix/main.cf /etc/postfix/main.cf.bak

    # 配置main.cf
    cat > /etc/postfix/main.cf <<EOF
myhostname = mail.$DOMAIN
mydomain = $DOMAIN
myorigin = \$mydomain
inet_interfaces = all
mydestination = \$myhostname, localhost.\$mydomain, localhost, \$mydomain
mynetworks = 127.0.0.0/8 [::ffff:127.0.0.0]/104 [::1]/128
home_mailbox = Maildir/
smtpd_sasl_type = dovecot
smtpd_sasl_path = private/auth
smtpd_sasl_auth_enable = yes
smtpd_recipient_restrictions = permit_sasl_authenticated, permit_mynetworks, reject_unauth_destination
smtpd_tls_cert_file = /etc/ssl/certs/mail-$DOMAIN-cert.pem
smtpd_tls_key_file = /etc/ssl/private/mail-$DOMAIN-key.pem
smtpd_use_tls = yes
smtpd_tls_session_cache_database = btree:\${data_directory}/smtpd_scache
smtp_tls_session_cache_database = btree:\${data_directory}/smtp_scache
EOF

    # 配置master.cf启用587端口
    # 彻底清理所有submission配置
    sed -i '/^[[:space:]]*submission/d' /etc/postfix/master.cf
    # 使用双引号here-document允许变量展开
    cat >> /etc/postfix/master.cf <<EOF
submission inet n       -       y       -       -       smtpd
  -o syslog_name=postfix/submission
  -o smtpd_tls_security_level=encrypt
  -o smtpd_sasl_auth_enable=yes
  -o smtpd_sasl_type=dovecot
  -o smtpd_sasl_path=private/auth
  -o smtpd_recipient_restrictions=permit_sasl_authenticated,reject
  -o milter_macro_daemon_name=ORIGINATING
  -o smtpd_tls_cert_file=/etc/ssl/certs/mail-$DOMAIN-cert.pem
  -o smtpd_tls_key_file=/etc/ssl/private/mail-$DOMAIN-key.pem
EOF

    # 使用兼容命令重启Postfix
    /etc/init.d/postfix restart

    # 检查Postfix状态和587端口监听
    echo "检查Postfix服务状态..."
    if ! /etc/init.d/postfix status; then
        echo "警告：Postfix服务未运行，检查日志获取详细信息"
        tail -n 20 /var/log/mail.log
    fi

    echo "验证Postfix配置..."
    if ! postfix check; then
        echo "错误：Postfix配置存在问题"
    fi

    echo "检查587端口监听情况..."
    if ! ss -tulpn | grep -q ':587'; then
        echo "错误：587端口未监听，检查Postfix submission配置"
        echo "Postfix submission配置："
        grep -A 10 'submission' /etc/postfix/master.cf
    fi
}

# 函数：配置Dovecot
configure_dovecot() {
    echo "正在配置Dovecot..."
    # 备份原始配置
    cp /etc/dovecot/dovecot.conf /etc/dovecot/dovecot.conf.bak

    # 配置dovecot.conf
    cat > /etc/dovecot/dovecot.conf <<EOF
protocols = imap pop3 lmtp
listen = *, ::

# SSL配置
ssl = required
ssl_cert = </etc/ssl/certs/mail-$DOMAIN-cert.pem
ssl_key = </etc/ssl/private/mail-$DOMAIN-key.pem

# 邮件存储位置和格式
mail_location = maildir:~/Maildir
mail_privileged_group = mail

# 认证配置
auth_mechanisms = plain login
passdb {
  driver = pam
}
userdb {
  driver = passwd
}

# 服务配置
service auth {
  unix_listener /var/spool/postfix/private/auth {
    mode = 0666
    user = postfix
    group = postfix
  }
}
EOF

    # 重启Dovecot
    service dovecot restart
}

# 函数：创建管理员用户
create_admin_user() {
    echo "正在创建管理员用户..."
    # 提取用户名（@前面的部分）
    USERNAME=$(echo "$ADMIN_EMAIL" | cut -d@ -f1)

    # 创建用户（如果不存在）
    if ! id -u "$USERNAME" >/dev/null 2>&1; then
        adduser --gecos "" --disabled-password "$USERNAME"
    fi

    # 设置密码
    echo "$USERNAME:$ADMIN_PASSWORD" | chpasswd

    # 确保Maildir目录存在
    mkdir -p /home/"$USERNAME"/Maildir
    chown -R "$USERNAME":"$USERNAME" /home/"$USERNAME"/Maildir
}

# 函数：创建普通用户
create_user() {
    local username="$1"
    local password="$2"

    echo "正在创建用户: $username"

    # 创建用户（如果不存在）
    if ! id -u "$username" >/dev/null 2>&1; then
        adduser --gecos "" --disabled-password "$username"
    else
        echo "用户 $username 已存在，仅更新密码"
    fi

    # 设置密码
    echo "$username:$password" | chpasswd

    # 确保Maildir目录存在
    mkdir -p /home/"$username"/Maildir
    chown -R "$username":"$username" /home/"$username"/Maildir
}

# 函数：设置服务开机自启
enable_services() {
    echo "正在设置服务开机自启..."
    update-rc.d postfix defaults
    update-rc.d dovecot defaults

    # 配置防火墙
    echo "正在配置防火墙..."
    ufw allow 25/tcp
    ufw allow 587/tcp
    ufw allow 993/tcp
    ufw allow 995/tcp
    ufw --force enable

    echo ""
}

# 函数：测试邮件发送
test_email() {
    echo "测试邮件发送功能..."
    echo "这是一封测试邮件。" | mail -s "测试邮件" "$ADMIN_EMAIL"
    echo "测试邮件已发送到 $ADMIN_EMAIL，请检查收件箱。"
}

# 主函数
main() {
    # 检查是否是添加用户模式
    if [ -n "$ADD_USER" ] && [ -n "$USER_PASSWORD" ]; then
        USERNAME=$(echo "$ADD_USER" | cut -d@ -f1)
        create_user "$USERNAME" "$USER_PASSWORD"
        echo "用户 $ADD_USER 创建成功"
        exit 0
    elif [ -n "$ADD_USER" ] || [ -n "$USER_PASSWORD" ]; then
        echo "错误：添加用户时必须同时提供--add-user和--user-password参数"
        show_help
        exit 1
    fi

    parse_args "$@"
    install_packages
    configure_postfix
    configure_dovecot
    create_admin_user
    enable_services

    # 重启服务使配置生效
    service dovecot restart
    service postfix restart

    echo ""
    echo "邮件系统部署完成！"
    echo "域名: $DOMAIN"
    echo "管理员邮箱: $ADMIN_EMAIL"
    echo "管理员密码: $ADMIN_PASSWORD"
    echo ""

    test_email
}

# 执行主函数
main "$@"
