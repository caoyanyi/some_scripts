# Ops Monitor

`ops_monitor.py` 是一个无第三方依赖的 Linux 运维监控脚本，用来做这些事情：

- 监测 1 分钟系统负载，并按 CPU 核心数归一化告警。
- 读取 `/sys/class/thermal` 或 `sensors -u` 做过热预警。
- 监测内存和磁盘使用率。
- 按配置匹配长期运行、CPU 长时间过高、`D` 状态的疑似卡死进程。
- 默认只告警；只有把 `dry_run` 设为 `false` 且进程规则 `action` 为 `terminate`/`kill` 时才会清理进程。
- 支持日志、告警冷却、Webhook 和 SMTP 邮件告警。
- SMTP 邮件支持 `none`、`starttls`、`ssl`，并支持用户名/密码认证。
- 每次巡检会写入 SQLite 历史库，可用内置仪表盘查看当前、近期和历史异常。
- 异常记录支持分页展示，并会合并相邻时间内重复出现的同类预警。

## 快速运行

```bash
python3 ops_monitor/ops_monitor.py --once --dry-run
```

建议先复制配置后再改阈值：

```bash
cp ops_monitor/config.example.json ops_monitor/config.json
python3 ops_monitor/ops_monitor.py -c ops_monitor/config.json --once --dry-run
```

确认规则不会误伤后，再允许自动清理：

```bash
python3 ops_monitor/ops_monitor.py -c ops_monitor/config.json --no-dry-run
```

启动本地仪表盘：

```bash
python3 ops_monitor/ops_dashboard.py -c ops_monitor/config.json --host 127.0.0.1 --port 8765
```

打开 `http://127.0.0.1:8765` 可以查看当前健康状态、关键指标、趋势图、活跃异常和历史异常。仪表盘读取 `history_db` 指向的 SQLite 文件。

## 配置要点

邮件通知配置示例：

```json
{
  "alerts": {
    "email": {
      "enabled": true,
      "smtp_host": "smtp.example.com",
      "smtp_port": 465,
      "security": "ssl",
      "username": "ops@example.com",
      "password_env": "DMD_OPS_MONITOR_SMTP_PASSWORD",
      "from": "ops@example.com",
      "to": ["admin@example.com"]
    }
  }
}
```

`security` 可选值：

- `none`: 普通 SMTP，常见端口 25。
- `starttls`: 先连接普通 SMTP，再升级 TLS，常见端口 587。
- `ssl`: 连接时直接使用 SSL/TLS，常见端口 465。

可以用 `password` 直接配置密码，也可以用 `password_env` 从环境变量读取。生产环境建议使用 `password_env`，不要把真实密码提交进仓库。

`processes` 数组定义需要重点关注的业务脚本：

- `match`: 必须全部出现在进程命令行里，才认为命中规则。
- `max_runtime_seconds`: 运行时间超过阈值后告警或清理。
- `max_cpu_percent` + `cpu_grace_seconds`: CPU 连续超过阈值一段时间后告警或清理。
- `action`: `alert` 只告警，`terminate` 先发 `SIGTERM`，超时后发 `SIGKILL`。
- `kill_after_seconds`: `SIGTERM` 后等待进程自行退出的秒数。

默认配置中清理处于 `dry_run` 模式，会记录“将要清理”的日志，但不会真正杀进程。

历史数据配置：

- `history_db`: SQLite 历史库路径，默认 `ops_monitor/ops-monitor.db`。
- `history_retention_days`: 历史保留天数，默认 30 天。
- `finding_dedup_seconds`: 相邻重复预警的写入去重窗口，默认 600 秒。

## systemd 部署

推荐使用一键部署脚本。脚本会自动根据自身位置获取项目路径，生成 systemd service；仓库目录移动后，重新执行一次即可刷新服务路径。

```bash
sudo bash ops_monitor/install.sh
```

常用命令：

```bash
sudo bash ops_monitor/install.sh --restart
sudo bash ops_monitor/install.sh --no-start
sudo bash ops_monitor/install.sh --status
sudo bash ops_monitor/install.sh --stop
sudo bash ops_monitor/install.sh --uninstall
```

指定仪表盘监听地址：

```bash
sudo bash ops_monitor/install.sh --port 8765
sudo bash ops_monitor/install.sh --host 127.0.0.1 --port 8765
sudo bash ops_monitor/install.sh --local-only --port 8765
sudo bash ops_monitor/install.sh --lan --port 8765
```

也可以手动部署，但需要先把 service 模板里的 `__PROJECT_DIR__` 替换成实际项目路径：

```bash
sudo install -d /etc/dmd
sudo cp ops_monitor/config.example.json /etc/dmd/ops-monitor.json
sudo sed "s#__PROJECT_DIR__#$(pwd)#g" ops_monitor/systemd/dmd-ops-monitor.service | sudo tee /etc/systemd/system/dmd-ops-monitor.service >/dev/null
sudo sed "s#__PROJECT_DIR__#$(pwd)#g" ops_monitor/systemd/dmd-ops-dashboard.service | sudo tee /etc/systemd/system/dmd-ops-dashboard.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now dmd-ops-monitor.service
sudo systemctl enable --now dmd-ops-dashboard.service
sudo journalctl -u dmd-ops-monitor.service -f
```

仪表盘 service 默认监听 `0.0.0.0:8765`，允许局域网设备通过服务器局域网 IP 访问。需要只允许本机访问时，使用 `--local-only` 或 `--host 127.0.0.1`。公网或跨网段访问建议通过 Nginx、SSH tunnel 或内网 VPN 暴露，并在外层增加访问控制。
