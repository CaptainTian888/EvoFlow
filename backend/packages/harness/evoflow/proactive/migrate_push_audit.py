"""Migration: Add feishu_push_audit table for comprehensive diagnostics."""

import sqlite3
from datetime import datetime

def migrate_add_push_audit_table(db_path: str):
    """Add evoflow_feishu_push_audit table."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    print("Creating evoflow_feishu_push_audit table...")
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS evoflow_feishu_push_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            
            -- Push source
            push_kind TEXT NOT NULL,
            triggered_by TEXT NOT NULL DEFAULT 'system',
            trigger_event TEXT,
            
            -- Source role
            source_agent_code TEXT NOT NULL,
            source_role_name TEXT,
            
            -- Target
            receive_id TEXT NOT NULL,
            receive_id_type TEXT NOT NULL,
            receive_id_label TEXT,
            
            -- Decision
            decision TEXT NOT NULL,
            decision_reason TEXT,
            
            -- Config snapshot
            source_approval_channels TEXT,
            source_push_policy_json TEXT,
            target_resolution_method TEXT,
            
            -- Result
            status TEXT NOT NULL,
            error_msg TEXT,
            feishu_message_id TEXT,
            
            -- Metadata
            request_id TEXT,
            gateway_pid INTEGER,
            created_at TEXT NOT NULL
        );
    """)
    
    # Create indexes
    cur.execute("CREATE INDEX IF NOT EXISTS idx_source_code_created ON evoflow_feishu_push_audit(source_agent_code, created_at DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_target_created ON evoflow_feishu_push_audit(receive_id, created_at DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_decision_created ON evoflow_feishu_push_audit(decision, created_at DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_created ON evoflow_feishu_push_audit(created_at DESC)")
    
    # Also create a convenience view for recent issues
    cur.execute("""
        CREATE VIEW IF NOT EXISTS v_recent_push_issues AS
        SELECT 
            created_at,
            push_kind,
            source_agent_code,
            receive_id,
            receive_id_label,
            decision,
            decision_reason,
            status,
            error_msg
        FROM evoflow_feishu_push_audit
        WHERE decision IN ('blocked', 'fallback') OR status = 'failed'
        ORDER BY created_at DESC
        LIMIT 100;
    """)
    
    conn.commit()
    print("OK: Table created")
    print("\nYou can now query push audit with:")
    print("  SELECT * FROM evoflow_feishu_push_audit WHERE source_agent_code = '...' ORDER BY created_at DESC")
    print("  SELECT * FROM v_recent_push_issues")
    
    conn.close()

if __name__ == '__main__':
    import sys
    db_path = sys.argv[1] if len(sys.argv) > 1 else r'C:\Users\admin\.evoflow-dev\data\app\evoflow.db'
    migrate_add_push_audit_table(db_path)
