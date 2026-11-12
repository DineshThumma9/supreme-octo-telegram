#!/usr/bin/env bash
# ==============================================================================
# Renvue - Tmux Development Services Launcher
# Starts Backend (FastAPI), Frontend (Vite), Taskiq Worker, and Taskiq Scheduler
# in a 4-quadrant tiled tmux session so all logs are simultaneously visible.
# ==============================================================================

set -euo pipefail

SESSION_NAME="${SESSION_NAME:-renvue}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="${SCRIPT_DIR}/backend"
FRONTEND_DIR="${SCRIPT_DIR}/frontend"

# Colors
C_RESET='\033[0m'
C_BOLD='\033[1m'
C_GREEN='\033[32m'
C_BLUE='\033[34m'
C_YELLOW='\033[33m'
C_RED='\033[31m'
C_CYAN='\033[36m'

log_info() {
    echo -e "${C_BLUE}${C_BOLD}[INFO]${C_RESET} $*"
}

log_success() {
    echo -e "${C_GREEN}${C_BOLD}[OK]${C_RESET} $*"
}

log_warn() {
    echo -e "${C_YELLOW}${C_BOLD}[WARN]${C_RESET} $*"
}

log_error() {
    echo -e "${C_RED}${C_BOLD}[ERROR]${C_RESET} $*"
}

print_help() {
    echo -e "${C_BOLD}Usage:${C_RESET} $0 [command] [options]

${C_BOLD}Commands:${C_RESET}
  start               Start all services in tmux (default action)
  stop, kill          Stop all running services and kill the tmux session
  restart             Stop the existing session and start a new one
  attach              Attach to an existing tmux session
  status              Check if the tmux session and services are running

${C_BOLD}Options:${C_RESET}
  -d, --detach        Start services in background without attaching
  -s, --session NAME  Specify tmux session name (default: renvue)
  -h, --help          Show this help message

${C_BOLD}Tmux Keybindings Quick Reference:${C_RESET}
  ${C_CYAN}Mouse Click${C_RESET}         Focus any pane / drag borders to resize
  ${C_CYAN}Mouse Scroll${C_RESET}        Scroll through service logs
  ${C_CYAN}Ctrl+b then arrows${C_RESET}  Navigate between panes
  ${C_CYAN}Ctrl+b then z${C_RESET}       Toggle full-screen zoom for focused pane
  ${C_CYAN}Ctrl+b then d${C_RESET}       Detach from tmux (services keep running)
  ${C_CYAN}Ctrl+c (in pane)${C_RESET}    Stop specific service without closing pane"
}

check_port() {
    local port="$1"
    timeout 1 bash -c "</dev/tcp/localhost/${port}" 2>/dev/null
}

check_prerequisites() {
    log_info "Checking prerequisites..."

    local missing=0
    for cmd in tmux uv npm; do
        if ! command -v "$cmd" >/dev/null 2>&1; then
            log_error "Missing required command: $cmd"
            missing=1
        fi
    done

    if [ "$missing" -ne 0 ]; then
        log_error "Please install the missing tools and try again."
        exit 1
    fi

    # Check directories
    if [ ! -d "$BACKEND_DIR" ]; then
        log_error "Backend directory not found at: $BACKEND_DIR"
        exit 1
    fi
    if [ ! -d "$FRONTEND_DIR" ]; then
        log_error "Frontend directory not found at: $FRONTEND_DIR"
        exit 1
    fi

    # Check infrastructure: Redis (6379) & Postgres (5432)
    local need_docker=0
    if ! check_port 6379; then
        log_warn "Redis is not reachable on localhost:6379."
        need_docker=1
    fi
    if ! check_port 5432; then
        log_warn "PostgreSQL is not reachable on localhost:5432."
        need_docker=1
    fi

    if [ "$need_docker" -eq 1 ]; then
        if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
            log_info "Starting PostgreSQL and Redis via docker compose..."
            (cd "$SCRIPT_DIR" && docker compose up -d)
            
            # Wait up to 5 seconds for ports to become available
            log_info "Waiting for database services to become ready..."
            for _ in {1..10}; do
                if check_port 6379 && check_port 5432; then
                    break
                fi
                sleep 0.5
            done
        else
            log_warn "Docker is not available or not running. Services may fail if Redis/Postgres are missing."
        fi
    fi

    log_success "Prerequisites verified."
}

is_session_running() {
    tmux has-session -t "$SESSION_NAME" 2>/dev/null
}

stop_session() {
    if is_session_running; then
        log_info "Stopping tmux session '${SESSION_NAME}'..."
        # Gracefully send SIGINT (Ctrl+C) to all panes
        local pane_ids
        pane_ids=$(tmux list-panes -t "$SESSION_NAME" -F "#{pane_id}" 2>/dev/null || true)
        for pane in $pane_ids; do
            tmux send-keys -t "$pane" C-c 2>/dev/null || true
        done
        sleep 1
        tmux kill-session -t "$SESSION_NAME" 2>/dev/null || true
        log_success "Tmux session '${SESSION_NAME}' stopped."
    else
        log_info "Tmux session '${SESSION_NAME}' is not running."
    fi
}

start_services() {
    local detach="$1"

    if is_session_running; then
        log_warn "Session '${SESSION_NAME}' is already running."
        if [ "$detach" = false ] && [ -t 0 ]; then
            log_info "Attaching to existing session '${SESSION_NAME}'..."
            attach_session
            return
        else
            log_info "To re-attach: tmux attach -t ${SESSION_NAME}"
            log_info "To restart:  $0 restart"
            return
        fi
    fi

    check_prerequisites

    log_info "Creating tmux session '${SESSION_NAME}'..."

    # 1. Start tmux session detached with window named 'services' in backend dir
    tmux new-session -d -s "$SESSION_NAME" -n "services" -c "$BACKEND_DIR"

    # Configure tmux options for better developer experience
    tmux set-option -t "$SESSION_NAME" mouse on
    tmux set-option -t "$SESSION_NAME" pane-border-status top
    tmux set-option -t "$SESSION_NAME" pane-border-format " #[bold]#{?#{==:#{pane_index},0}, Backend API (FastAPI :8000) ,#{?#{==:#{pane_index},1}, Frontend UI (Vite :5173) ,#{?#{==:#{pane_index},2}, Taskiq Worker (Broker) , Taskiq Scheduler }}}#[default] "
    tmux set-option -t "$SESSION_NAME" pane-border-style "fg=colour242"
    tmux set-option -t "$SESSION_NAME" pane-active-border-style "fg=colour39,bold"
    tmux set-option -t "$SESSION_NAME" status-left " #[bold]#[fg=colour75]${SESSION_NAME}#[default] "
    tmux set-option -t "$SESSION_NAME" status-right " #[fg=colour245]%H:%M #[fg=colour75]| 4 Services Active #[default]"

    # 2. Split window into 4 quadrants (2x2 grid)
    # Current state: Pane 0 (full window)
    tmux split-window -v -t "${SESSION_NAME}:services.0" -c "$BACKEND_DIR"
    # State: Pane 0 (Top), Pane 1 (Bottom)
    tmux split-window -h -t "${SESSION_NAME}:services.0" -c "$FRONTEND_DIR"
    # State: Pane 0 (Top-Left), Pane 1 (Top-Right), Pane 2 (Bottom)
    tmux split-window -h -t "${SESSION_NAME}:services.2" -c "$BACKEND_DIR"
    # State: Pane 0 (Top-Left), Pane 1 (Top-Right), Pane 2 (Bottom-Left), Pane 3 (Bottom-Right)

    # Balance into clean 2x2 grid
    tmux select-layout -t "${SESSION_NAME}:services" tiled

    # 3. Launch processes in each pane
    # Pane 0: Backend API
    tmux send-keys -t "${SESSION_NAME}:services.0" "cd \"$BACKEND_DIR\" && uv run uvicorn src.main:app --reload --port 8000" C-m

    # Pane 1: Frontend
    tmux send-keys -t "${SESSION_NAME}:services.1" "cd \"$FRONTEND_DIR\" && npm run dev" C-m

    # Pane 2: Taskiq Worker
    tmux send-keys -t "${SESSION_NAME}:services.2" "cd \"$BACKEND_DIR\" && uv run taskiq worker -d src background.worker:broker" C-m

    # Pane 3: Taskiq Scheduler
    tmux send-keys -t "${SESSION_NAME}:services.3" "cd \"$BACKEND_DIR\" && uv run taskiq scheduler -d src background.worker:scheduler" C-m

    sleep 0.2

    # 4. Set pane titles for the status borders
    tmux select-pane -t "${SESSION_NAME}:services.0" -T "Backend API (FastAPI - http://localhost:8000)"
    tmux select-pane -t "${SESSION_NAME}:services.1" -T "Frontend (Vite - http://localhost:5173)"
    tmux select-pane -t "${SESSION_NAME}:services.2" -T "Taskiq Worker (background.worker:broker)"
    tmux select-pane -t "${SESSION_NAME}:services.3" -T "Taskiq Scheduler (background.worker:scheduler)"

    # Focus Top-Left (Backend)
    tmux select-pane -t "${SESSION_NAME}:services.0"

    log_success "All 4 services launched in tmux session '${SESSION_NAME}':"
    echo -e "  ${C_CYAN}Top-Left:${C_RESET}     Backend API     (uvicorn src.main:app --reload --port 8001)"
    echo -e "  ${C_CYAN}Top-Right:${C_RESET}    Frontend UI     (npm run dev -> http://localhost:5173)"
    echo -e "  ${C_CYAN}Bottom-Left:${C_RESET}  Taskiq Worker   (taskiq worker -d src background.worker:broker)"
    echo -e "  ${C_CYAN}Bottom-Right:${C_RESET} Taskiq Sched    (taskiq scheduler -d src background.worker:scheduler)"
    echo ""

    if [ "$detach" = true ] || [ ! -t 0 ]; then
        log_info "Running in detached mode."
        log_info "To view services: ${C_BOLD}tmux attach -t ${SESSION_NAME}${C_RESET}"
        log_info "To stop services: ${C_BOLD}$0 stop${C_RESET}"
    else
        attach_session
    fi
}

attach_session() {
    if ! is_session_running; then
        log_error "Session '${SESSION_NAME}' is not running. Start it first with '$0 start'."
        exit 1
    fi

    if [ -n "${TMUX:-}" ]; then
        tmux switch-client -t "$SESSION_NAME"
    else
        tmux attach-session -t "$SESSION_NAME"
    fi
}

# Parse Arguments
ACTION="start"
DETACH=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        start)
            ACTION="start"
            shift
            ;;
        stop|kill)
            ACTION="stop"
            shift
            ;;
        restart)
            ACTION="restart"
            shift
            ;;
        attach)
            ACTION="attach"
            shift
            ;;
        status)
            ACTION="status"
            shift
            ;;
        -d|--detach|--no-attach)
            DETACH=true
            shift
            ;;
        -s|--session)
            SESSION_NAME="$2"
            shift 2
            ;;
        -h|--help)
            print_help
            exit 0
            ;;
        *)
            log_error "Unknown option or command: $1"
            print_help
            exit 1
            ;;
    esac
done

case "$ACTION" in
    start)
        start_services "$DETACH"
        ;;
    stop)
        stop_session
        ;;
    restart)
        stop_session
        sleep 0.5
        start_services "$DETACH"
        ;;
    attach)
        attach_session
        ;;
    status)
        if is_session_running; then
            log_success "Tmux session '${SESSION_NAME}' is active."
            echo -e "  ${C_CYAN}Pane 0 [Top-Left]:${C_RESET}     Backend API     (:8000)"
            echo -e "  ${C_CYAN}Pane 1 [Top-Right]:${C_RESET}    Frontend UI     (:5173)"
            echo -e "  ${C_CYAN}Pane 2 [Bottom-Left]:${C_RESET}  Taskiq Worker   (Broker)"
            echo -e "  ${C_CYAN}Pane 3 [Bottom-Right]:${C_RESET} Taskiq Sched    (Scheduler)"
            echo ""
            log_info "To view services: ${C_BOLD}tmux attach -t ${SESSION_NAME}${C_RESET}"
            log_info "To stop services: ${C_BOLD}$0 stop${C_RESET}"
        else
            log_info "Tmux session '${SESSION_NAME}' is not running."
        fi
        ;;
esac
