#!/bin/bash

echo '配置gitlab克隆代码使用443端口'
if [ ! -d ~/.ssh ]; then
    mkdir ~/.ssh
fi

cat <<'EOF' >> ~/.ssh/config
Host github.com
HostName ssh.github.com
User git
Port 443
PreferredAuthentications publickey
EOF

if [ -f ~/.ssh/id_rsa ]; then
    echo 'IdentityFile ~/.ssh/id_rsa' >> ~/.ssh/config
    echo '请将 ~/.ssh/id_rsa.pub 复制到 https://github.com/settings/keys'
elif [ -f ~/.ssh/id_ed25519 ]; then
    echo 'IdentityFile ~/.ssh/id_ed25519' >> ~/.ssh/config
    echo '请将 ~/.ssh/id_ed25519.pub 复制到 https://github.com/settings/keys'
else
    rm -f ~/.ssh/config
    echo '请生成 ~/.ssh/id_rsa 或 ~/.ssh/id_ed25519，执行 ssh-keygen 命令生成公钥'
fi
chmod 600 ~/.ssh/config

echo '配置完成，测试ssh连接'
ssh -T git@github.com
