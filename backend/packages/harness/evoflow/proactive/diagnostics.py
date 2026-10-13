"""Diagnostics tools for Feishu push system."""

import sqlite3
import json
from datetime import datetime, timedelta
from typing import Any

class FeishuPushDiagnostics:
    """Comprehensive diagnostics for Feishu push issues."""
    
    def __init__(self, db_path: str):
        self.db = sqlite3.connect(db_path)
        self.db.row_factory = sqlite3.Row
    
    def trace_agent_pushes(self, agent_code: str, minutes: int = 120) -> list[dict]:
        """Trace all push attempts for a role."""
        cutoff = datetime.utcnow() - timedelta(minutes=minutes)
        cur = self.db.execute("""
            SELECT 
                created_at, push_kind, decision, decision_reason,
                receive_id, receive_id_label, receive_id_type,
                target_resolution_method, status, error_msg
            FROM evoflow_feishu_push_audit
            WHERE source_agent_code = ? AND created_at > ?
            ORDER BY created_at DESC
        """, (agent_code, cutoff.isoformat()))
        
        return [dict(row) for row in cur.fetchall()]
    
    def trace_target_receives(self, receive_id: str, minutes: int = 120) -> list[dict]:
        """Trace all push attempts to a specific target."""
        cutoff = datetime.utcnow() - timedelta(minutes=minutes)
        cur = self.db.execute("""
            SELECT 
                created_at, push_kind, decision, source_agent_code, source_role_name,
                decision_reason, target_resolution_method, status, error_msg
            FROM evoflow_feishu_push_audit
            WHERE receive_id = ? AND created_at > ?
            ORDER BY created_at DESC
        """, (receive_id, cutoff.isoformat()))
        
        return [dict(row) for row in cur.fetchall()]
    
    def find_blocking_issues(self, minutes: int = 120) -> list[dict]:
        """Find all blocked/failed pushes."""
        cutoff = datetime.utcnow() - timedelta(minutes=minutes)
        cur = self.db.execute("""
            SELECT 
                created_at, push_kind, source_agent_code,
                receive_id, receive_id_label, decision_reason, error_msg, status
            FROM evoflow_feishu_push_audit
            WHERE (decision = 'blocked' OR status = 'failed') AND created_at > ?
            ORDER BY created_at DESC
        """, (cutoff.isoformat(),))
        
        return [dict(row) for row in cur.fetchall()]
    
    def compare_pair(self, agent_code: str, receive_id: str) -> dict[str, Any]:
        """Compare push history between a role and target."""
        cur = self.db.execute("""
            SELECT 
                created_at, push_kind, decision, decision_reason,
                source_approval_channels, target_resolution_method, status
            FROM evoflow_feishu_push_audit
            WHERE source_agent_code = ? AND receive_id = ?
            ORDER BY created_at DESC LIMIT 10
        """, (agent_code, receive_id))
        
        return {
            "agent_code": agent_code,
            "receive_id": receive_id,
            "history": [dict(row) for row in cur.fetchall()],
        }
    
    def summarize_recent(self, minutes: int = 60) -> dict[str, Any]:
        """Summarize recent push activity."""
        cutoff = datetime.utcnow() - timedelta(minutes=minutes)
        
        # By decision
        cur = self.db.execute("""
            SELECT decision, COUNT(*) as count, COUNT(DISTINCT source_agent_code) as agents
            FROM evoflow_feishu_push_audit
            WHERE created_at > ?
            GROUP BY decision
        """, (cutoff.isoformat(),))
        
        by_decision = {}
        for row in cur.fetchall():
            by_decision[row['decision']] = {
                'count': row['count'],
                'unique_agents': row['agents']
            }
        
        # By kind
        cur = self.db.execute("""
            SELECT push_kind, COUNT(*) as count
            FROM evoflow_feishu_push_audit
            WHERE created_at > ?
            GROUP BY push_kind
        """, (cutoff.isoformat(),))
        
        by_kind = {}
        for row in cur.fetchall():
            by_kind[row['push_kind']] = row['count']
        
        return {
            "period": f"last {minutes} minutes",
            "by_decision": by_decision,
            "by_kind": by_kind,
        }
    
    def print_agent_trace(self, agent_code: str, minutes: int = 120):
        """Print formatted trace for a role."""
        trace = self.trace_agent_pushes(agent_code, minutes)
        
        print(f"\n{'='*80}")
        print(f"AGENT: {agent_code}")
        print(f"{'='*80}")
        print(f"Push attempts (last {minutes} min):\n")
        
        if not trace:
            print("  (no push attempts)")
            return
        
        for entry in trace:
            print(f"  {entry['created_at']:20s} | {entry['push_kind']:15s} | {entry['decision']:10s}")
            print(f"    → {entry['receive_id_label'] or entry['receive_id']}")
            print(f"    Method: {entry['target_resolution_method']}")
            print(f"    Status: {entry['status']}")
            if entry['decision_reason']:
                print(f"    Reason: {entry['decision_reason']}")
            if entry['error_msg']:
                print(f"    Error: {entry['error_msg']}")
            print()
    
    def print_target_trace(self, receive_id: str, minutes: int = 120):
        """Print formatted trace for a target."""
        trace = self.trace_target_receives(receive_id, minutes)
        
        print(f"\n{'='*80}")
        print(f"TARGET: {receive_id}")
        print(f"{'='*80}")
        print(f"Incoming push attempts (last {minutes} min):\n")
        
        if not trace:
            print("  (no push attempts)")
            return
        
        # Group by agent
        by_agent = {}
        for entry in trace:
            agent = entry['source_agent_code']
            by_agent.setdefault(agent, []).append(entry)
        
        for agent in sorted(by_agent.keys()):
            print(f"  Agent: {agent}")
            for entry in by_agent[agent]:
                print(f"    {entry['created_at']:20s} | {entry['push_kind']:15s} | {entry['decision']:10s}")
                if entry['decision_reason']:
                    print(f"      Reason: {entry['decision_reason']}")
            print()
    
    def print_issues(self, minutes: int = 120):
        """Print all blocking/failed issues."""
        issues = self.find_blocking_issues(minutes)
        
        print(f"\n{'='*80}")
        print(f"BLOCKING ISSUES (last {minutes} min)")
        print(f"{'='*80}\n")
        
        if not issues:
            print("  (no issues found)")
            return
        
        for issue in issues:
            print(f"  [{issue['status'].upper()}] {issue['created_at']}")
            print(f"    From: {issue['source_agent_code']}")
            print(f"    Kind: {issue['push_kind']}")
            print(f"    Target: {issue['receive_id_label'] or issue['receive_id']}")
            if issue['decision_reason']:
                print(f"    Reason: {issue['decision_reason']}")
            if issue['error_msg']:
                print(f"    Error: {issue['error_msg']}")
            print()
    
    def query_raw(self, sql: str):
        """Execute raw SQL query for debugging."""
        cur = self.db.execute(sql)
        rows = cur.fetchall()
        
        if not rows:
            print("(no results)")
            return
        
        # Print header
        cols = [description[0] for description in cur.description]
        print("  ".join(f"{c:20s}" for c in cols))
        print("-" * (22 * len(cols)))
        
        # Print rows
        for row in rows:
            print("  ".join(f"{str(v)[:20]:20s}" for v in row))
