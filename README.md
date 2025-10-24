# 实用脚本集合

本仓库包含一系列实用的脚本工具，用于系统管理、服务器部署、安全配置等任务。

## 脚本列表

### 1. WSL-PortManager.ps1

**功能**：WSL端口转发管理工具

- 交互式菜单操作
- 单端口/批量添加与删除转发规则
- 清空所有转发规则
- 查看WSL状态与系统信息
- 管理员权限自动检测
- 输入验证与实时反馈

**使用方法**：以管理员身份运行PowerShell，执行该脚本即可进入交互式菜单，如果有报错，可以转换编码为utf8或者utf8-bom格式。

```bash
Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
.\WSL-PortManager.ps1
```

### 2. deploy_mail_server.sh

**功能**：自动化邮件服务器部署脚本

- 配置邮件服务器域名
- 设置管理员邮箱和密码
- 安装Postfix和Dovecot等必要组件
- 生成域名特定的SSL证书
- 支持添加新用户

**使用方法**：

```bash
chmod +x deploy_mail_server.sh
./deploy_mail_server.sh --domain <域名> --email <管理员邮箱> --password <管理员密码>
```

### 3. frp.sh

**功能**：FRP(Fast Reverse Proxy)服务端安装配置脚本

- 自动下载指定版本的FRP
- 配置服务端监听端口和认证
- 设置Web管理界面
- 支持自定义端口配置
- 提供卸载功能

**使用方法**：

```bash
chmod +x frp.sh
./frp.sh -k <连接密钥> [-v 版本号] [-p 监听端口] [-w web端口]
```

### 4. github_ssh.sh

**功能**：GitHub SSH连接配置工具

- 配置GitHub使用443端口进行SSH连接（适用于某些限制22端口的网络环境）
- 自动检测并配置SSH密钥文件
- 生成正确的.ssh/config文件
- 测试SSH连接

**使用方法**：

```bash
chmod +x github_ssh.sh
./github_ssh.sh
```

### 5. safe.sh

**功能**：Linux系统安全加固脚本

- 设置shell连接超时（符合等保要求）
- 移除危险文件的suid/sgid权限
- 配置SSH安全选项（禁用弱协议、设置空闲超时）
- 开启TCP-SYNcookie保护
- 设置密码复杂度要求和账户锁定策略
- 配置审计日志
- 防止IP欺骗

**使用方法**：

```bash
chmod +x safe.sh
sudo ./safe.sh
```

### 6. smb/smb_deploy.sh

**功能**：SMB服务一键部署与优化脚本

- 自动安装Samba服务及相关工具
- 配置共享目录和Samba用户
- 优化SMB性能参数
- 支持外接硬盘自动挂载配置
- 配置防火墙规则
- 创建性能监控脚本
**使用方法**：

```bash
chmod +x smb/smb_deploy.sh
sudo ./smb/smb_deploy.sh
```

### 7. smb/performance_tuner.sh

**功能**：SMB性能调优脚本

- 优化网络参数（提高缓冲区大小）
- 配置磁盘I/O优化
- 内存使用优化
- 生成性能测试脚本
**使用方法**：

```bash
chmod +x smb/performance_tuner.sh
sudo ./smb/performance_tuner.sh
```

## 注意事项

1. 部分脚本需要root或管理员权限才能正常执行，请确保以适当权限运行
2. 在生产环境使用前，请先在测试环境验证脚本功能
3. 建议在执行前阅读脚本内容，了解其具体操作和潜在影响
4. 部分脚本会修改系统配置文件，请确保备份重要数据

## 系统要求

- Shell脚本：Linux系统（Ubuntu/Debian/CentOS等）
- PowerShell脚本：Windows系统，需安装WSL

## 许可证

本仓库中的脚本仅供学习和参考使用。
