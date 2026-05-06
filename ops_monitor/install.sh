#!/usr/bin/env bash
set -euo pipefail

SERVICE_DIR="/etc/systemd/system"
CONFIG_DIR="/etc/dmd"
CONFIG_FILE="${CONFIG_DIR}/ops-monitor.json"
MONITOR_SERVICE="dmd-ops-monitor.service"
DASHBOARD_SERVICE="dmd-ops-dashboard.service"
DASHBOARD_HOST="127.0.0.1"
DASHBOARD_PORT="8765"
ACTION="install"
START_SERVICES="yes"

usage() {
    cat <<'USAGE'
Usage: ops_monitor/install.sh [options]

Options:
  --install            Install/update services and start them (default)
  --no-start           Install/update services without starting them
  --restart            Install/update services and restart them
  --stop               Stop both services
  --uninstall          Stop, disable, and remove both service files
  --status             Show systemd status for both services
  --host HOST          Dashboard bind host (default: 127.0.0.1)
  --port PORT          Dashboard bind port (default: 8765)
  --config FILE        Config path (default: /etc/dmd/ops-monitor.json)
  -h, --help           Show this help
USAGE
}

log() {
    printf '[INFO] %s\n' "$*"
}

die() {
    printf '[ERROR] %s\n' "$*" >&2
    exit 1
}

require_root_for_write() {
    if [[ "${EUID}" -ne 0 ]]; then
        die "Please run as root: sudo $0 $*"
    fi
}

escape_systemd_path() {
    local value="$1"
    value="${value//\\/\\\\}"
    value="${value// /\\x20}"
    value="${value//$'\t'/\\x09}"
    printf '%s' "$value"
}

escape_systemd_arg() {
    local value="$1"
    value="${value//\\/\\\\}"
    value="${value//\"/\\\"}"
    printf '"%s"' "$value"
}

resolve_paths() {
    local script_source="${BASH_SOURCE[0]}"
    while [[ -L "$script_source" ]]; do
        local script_dir
        script_dir="$(cd -P "$(dirname "$script_source")" >/dev/null 2>&1 && pwd)"
        script_source="$(readlink "$script_source")"
        [[ "$script_source" != /* ]] && script_source="${script_dir}/${script_source}"
    done

    OPS_DIR="$(cd -P "$(dirname "$script_source")" >/dev/null 2>&1 && pwd)"
    PROJECT_DIR="$(cd "${OPS_DIR}/.." >/dev/null 2>&1 && pwd)"
    MONITOR_SCRIPT="${OPS_DIR}/ops_monitor.py"
    DASHBOARD_SCRIPT="${OPS_DIR}/ops_dashboard.py"
    CONFIG_EXAMPLE="${OPS_DIR}/config.example.json"
}

validate_files() {
    [[ -f "$MONITOR_SCRIPT" ]] || die "Missing monitor script: $MONITOR_SCRIPT"
    [[ -f "$DASHBOARD_SCRIPT" ]] || die "Missing dashboard script: $DASHBOARD_SCRIPT"
    [[ -f "$CONFIG_EXAMPLE" ]] || die "Missing config example: $CONFIG_EXAMPLE"
    command -v python3 >/dev/null 2>&1 || die "python3 is required"
    command -v systemctl >/dev/null 2>&1 || die "systemctl is required"
}

write_config_if_missing() {
    install -d "$CONFIG_DIR"
    if [[ -f "$CONFIG_FILE" ]]; then
        log "Keeping existing config: $CONFIG_FILE"
        return
    fi

    install -m 600 "$CONFIG_EXAMPLE" "$CONFIG_FILE"
    log "Created config: $CONFIG_FILE"
}

write_services() {
    local escaped_project_dir escaped_monitor_script escaped_dashboard_script escaped_config_file
    escaped_project_dir="$(escape_systemd_path "$PROJECT_DIR")"
    escaped_monitor_script="$(escape_systemd_arg "$MONITOR_SCRIPT")"
    escaped_dashboard_script="$(escape_systemd_arg "$DASHBOARD_SCRIPT")"
    escaped_config_file="$(escape_systemd_arg "$CONFIG_FILE")"

    cat > "${SERVICE_DIR}/${MONITOR_SERVICE}" <<EOF_SERVICE
[Unit]
Description=DMD system operations monitor
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${escaped_project_dir}
ExecStart=/usr/bin/env python3 ${escaped_monitor_script} -c ${escaped_config_file}
Restart=always
RestartSec=10
User=root
Nice=5

[Install]
WantedBy=multi-user.target
EOF_SERVICE

    cat > "${SERVICE_DIR}/${DASHBOARD_SERVICE}" <<EOF_SERVICE
[Unit]
Description=DMD ops monitor dashboard
After=network-online.target ${MONITOR_SERVICE}
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${escaped_project_dir}
ExecStart=/usr/bin/env python3 ${escaped_dashboard_script} -c ${escaped_config_file} --host ${DASHBOARD_HOST} --port ${DASHBOARD_PORT}
Restart=always
RestartSec=10
User=root
Nice=5

[Install]
WantedBy=multi-user.target
EOF_SERVICE

    chmod 644 "${SERVICE_DIR}/${MONITOR_SERVICE}" "${SERVICE_DIR}/${DASHBOARD_SERVICE}"
    log "Wrote ${SERVICE_DIR}/${MONITOR_SERVICE}"
    log "Wrote ${SERVICE_DIR}/${DASHBOARD_SERVICE}"
}

install_services() {
    require_root_for_write "$@"
    validate_files
    write_config_if_missing
    write_services
    systemctl daemon-reload
    systemctl enable "$MONITOR_SERVICE" "$DASHBOARD_SERVICE"

    if [[ "$START_SERVICES" == "yes" ]]; then
        systemctl restart "$MONITOR_SERVICE" "$DASHBOARD_SERVICE"
        log "Services restarted"
    else
        log "Services installed but not started"
    fi

    log "Dashboard: http://${DASHBOARD_HOST}:${DASHBOARD_PORT}"
    log "Config: $CONFIG_FILE"
}

stop_services() {
    require_root_for_write "$@"
    systemctl stop "$DASHBOARD_SERVICE" "$MONITOR_SERVICE" || true
    log "Services stopped"
}

uninstall_services() {
    require_root_for_write "$@"
    systemctl stop "$DASHBOARD_SERVICE" "$MONITOR_SERVICE" || true
    systemctl disable "$DASHBOARD_SERVICE" "$MONITOR_SERVICE" || true
    rm -f "${SERVICE_DIR}/${DASHBOARD_SERVICE}" "${SERVICE_DIR}/${MONITOR_SERVICE}"
    systemctl daemon-reload
    log "Service files removed. Config was preserved: $CONFIG_FILE"
}

show_status() {
    systemctl status "$MONITOR_SERVICE" "$DASHBOARD_SERVICE" --no-pager || true
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --install)
                ACTION="install"
                START_SERVICES="yes"
                ;;
            --no-start)
                ACTION="install"
                START_SERVICES="no"
                ;;
            --restart)
                ACTION="install"
                START_SERVICES="yes"
                ;;
            --stop)
                ACTION="stop"
                ;;
            --uninstall)
                ACTION="uninstall"
                ;;
            --status)
                ACTION="status"
                ;;
            --host)
                shift
                [[ $# -gt 0 ]] || die "--host requires a value"
                DASHBOARD_HOST="$1"
                ;;
            --port)
                shift
                [[ $# -gt 0 ]] || die "--port requires a value"
                DASHBOARD_PORT="$1"
                ;;
            --config)
                shift
                [[ $# -gt 0 ]] || die "--config requires a value"
                CONFIG_FILE="$1"
                CONFIG_DIR="$(dirname "$CONFIG_FILE")"
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            *)
                die "Unknown option: $1"
                ;;
        esac
        shift
    done
}

main() {
    parse_args "$@"
    resolve_paths

    case "$ACTION" in
        install)
            install_services "$@"
            ;;
        stop)
            stop_services "$@"
            ;;
        uninstall)
            uninstall_services "$@"
            ;;
        status)
            show_status
            ;;
        *)
            die "Unknown action: $ACTION"
            ;;
    esac
}

main "$@"
