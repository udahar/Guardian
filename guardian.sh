#!/bin/bash
# Guardian Launcher - Shell Script (Linux/Mac)
# Automated system health monitoring and maintenance
# Note: Some features require WSL or Windows-specific tools

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

MODE="${1:-menu}"

show_menu() {
    echo ""
    echo "========================================"
    echo "       Guardian System Health          "
    echo "========================================"
    echo ""
    echo "  [1] Start AI Guardian (Recommended)"
    echo "  [2] Continuous Monitor"
    echo "  [3] Run Diagnostics"
    echo "  [4] Quick Cleanup"
    echo "  [5] Decision History"
    echo "  [6] Show Trends"
    echo "  [7] Pattern Analysis"
    echo "  [Q] Quit"
    echo ""
    read -p "Select option: " choice
}

case "$MODE" in
    help|--help|-h)
        echo "Guardian Command Line Usage:"
        echo ""
        echo "  ./guardian.sh ai           - Make AI decision"
        echo "  ./guardian.sh monitor      - Continuous monitoring"
        echo "  ./guardian.sh diagnose    - Run diagnostics"
        echo "  ./guardian.sh cleanup      - Quick cleanup"
        echo "  ./guardian.sh history      - Show decision history"
        echo "  ./guardian.sh trends       - Show trends"
        echo "  ./guardian.sh patterns    - Pattern analysis"
        echo ""
        ;;
    
    ai)
        echo "Starting AI Guardian..."
        python3 -m Guardian.ai_guardian --decision
        ;;
    
    monitor)
        echo "Starting Guardian Monitor..."
        echo "Press Ctrl+C to stop"
        python3 -m Guardian.windows_guardian
        ;;
    
    diagnose)
        echo "Running System Diagnostics..."
        python3 -m Guardian.diagnostics --print
        ;;
    
    cleanup)
        echo "Running Cleanup..."
        python3 -c "from Guardian import cleanup_all; import json; print(json.dumps(cleanup_all(), indent=2))"
        ;;
    
    history)
        echo "Decision History:"
        python3 -c "
from Guardian.db_manager import create_db
db = create_db()
hist = db.get_decision_history(7)
for h in hist[:15]:
    ts = h.get('timestamp', 'N/A')[:19]
    decision = h.get('decision', 'unknown')
    conf = h.get('confidence', 'N/A')
    print(f'{ts} - {decision} ({conf})')
"
        ;;
    
    trends)
        echo "Trends (30 days):"
        python3 -c "from Guardian.db_manager import create_db; import json; print(json.dumps(create_db().get_trends(30), indent=2))"
        ;;
    
    patterns)
        echo "Pattern Analysis:"
        python3 -c "from Guardian.db_manager import create_db; import json; print(json.dumps(create_db().get_patterns(), indent=2))"
        ;;
    
    menu)
        while true; do
            show_menu
            
            case "$choice" in
                1) python3 -m Guardian.ai_guardian --decision ;;
                2) python3 -m Guardian.windows_guardian ;;
                3) python3 -m Guardian.diagnostics --print ;;
                4) python3 -c "from Guardian import cleanup_all; import json; print(json.dumps(cleanup_all(), indent=2))" ;;
                5) python3 -c "
from Guardian.db_manager import create_db
db = create_db()
hist = db.get_decision_history(7)
for h in hist[:15]:
    print(f\"{h.get('timestamp','')[:19]} - {h.get('decision')} ({h.get('confidence')})\")
" ;;
                6) python3 -c "from Guardian.db_manager import create_db; import json; print(json.dumps(create_db().get_trends(30), indent=2))" ;;
                7) python3 -c "from Guardian.db_manager import create_db; import json; print(json.dumps(create_db().get_patterns(), indent=2))" ;;
                Q|q) 
                    echo "Goodbye!"
                    exit 0
                    ;;
                *) 
                    echo "Invalid option"
                    ;;
            esac
            
            if [ "$choice" != "2" ]; then
                echo ""
                read -p "Press Enter to continue"
            fi
        done
        ;;
    
    *)
        echo "Unknown option: $MODE"
        echo "Run './guardian.sh help' for usage"
        ;;
esac
