#!/usr/bin/env python3
"""Quick diagnostic CLI for Feishu push issues."""

import sys
from pathlib import Path
from diagnostics import FeishuPushDiagnostics

def main():
    if len(sys.argv) < 2:
        print_help()
        return
    
    cmd = sys.argv[1]
    db_path = Path.home() / ".evoflow-dev/data/app/evoflow.db"
    
    if not db_path.exists():
        print(f"Error: Database not found at {db_path}")
        return
    
    diag = FeishuPushDiagnostics(str(db_path))
    
    if cmd == "agent" and len(sys.argv) > 2:
        agent_code = sys.argv[2]
        minutes = int(sys.argv[3]) if len(sys.argv) > 3 else 120
        diag.print_agent_trace(agent_code, minutes)
    
    elif cmd == "target" and len(sys.argv) > 2:
        receive_id = sys.argv[2]
        minutes = int(sys.argv[3]) if len(sys.argv) > 3 else 120
        diag.print_target_trace(receive_id, minutes)
    
    elif cmd == "issues":
        minutes = int(sys.argv[2]) if len(sys.argv) > 2 else 120
        diag.print_issues(minutes)
    
    elif cmd == "summary":
        minutes = int(sys.argv[2]) if len(sys.argv) > 2 else 60
        summary = diag.summarize_recent(minutes)
        print(f"\nPush Summary (last {minutes} min)")
        print("=" * 60)
        print("\nBy Decision:")
        for decision, data in summary['by_decision'].items():
            print(f"  {decision:10s}: {data['count']:3d} attempts, {data['unique_agents']:2d} agents")
        print("\nBy Kind:")
        for kind, count in summary['by_kind'].items():
            print(f"  {kind:20s}: {count:3d}")
    
    elif cmd == "pair" and len(sys.argv) > 3:
        agent_code = sys.argv[2]
        receive_id = sys.argv[3]
        result = diag.compare_pair(agent_code, receive_id)
        
        print(f"\n{'='*80}")
        print(f"PAIR: {agent_code} <-> {receive_id}")
        print(f"{'='*80}\n")
        
        if not result['history']:
            print("  (no interaction history)")
            return
        
        for entry in result['history']:
            print(f"  {entry['created_at']:20s} | {entry['decision']:10s} | {entry['push_kind']:15s}")
            if entry['decision_reason']:
                print(f"    {entry['decision_reason']}")
            print()
    
    elif cmd == "sql" and len(sys.argv) > 2:
        sql = " ".join(sys.argv[2:])
        print()
        diag.query_raw(sql)
    
    elif cmd == "help":
        print_help()
    
    else:
        print(f"Unknown command: {cmd}")
        print_help()

def print_help():
    print("""
Feishu Push Diagnostics CLI

Usage:
  python diagnose_feishu_push.py <command> [options]

Commands:
  agent <agent_code> [minutes]     Trace pushes from a specific agent
  target <receive_id> [minutes]    Trace pushes to a specific chat/dm
  issues [minutes]                 Show all blocked/failed pushes
  summary [minutes]                Quick summary of push activity
  pair <agent> <target>            Compare interaction history between agent and target
  sql <query>                      Execute raw SQL query
  help                             Show this help

Examples:
  # Trace video-analyst's pushes in the last 2 hours
  python diagnose_feishu_push.py agent video-analyst 120
  
  # See all pushes to your chat
  python diagnose_feishu_push.py target oc_ec754692847407e341974cb14272a9d8
  
  # Find all currently blocked pushes
  python diagnose_feishu_push.py issues
  
  # Compare video-analyst vs your chat
  python diagnose_feishu_push.py pair video-analyst oc_ec754692847407e341974cb14272a9d8
  
  # Raw SQL query
  python diagnose_feishu_push.py sql "SELECT COUNT(*) FROM evoflow_feishu_push_audit"
    """)

if __name__ == '__main__':
    main()
