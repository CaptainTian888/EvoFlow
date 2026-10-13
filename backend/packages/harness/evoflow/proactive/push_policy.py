"""Role push configuration policy — single source of truth for push routing."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Literal
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

ChannelType = Literal["feishu", "wecom", "slack", "email"]
FeishuTargetType = Literal["open_id", "chat_id", "user_id"]


@dataclass
class ChannelBinding:
    """Configuration for one channel's push binding."""
    
    channel: ChannelType
    enabled: bool = True
    target_id: str = ""  # open_id, chat_id, user_id, email, etc.
    target_type: str = ""  # 'open_id' | 'chat_id' | 'user_id' | etc.
    verified_at: str | None = None  # ISO8601 timestamp
    
    def is_valid(self) -> bool:
        """Check if this binding is configured and ready to use."""
        return self.enabled and bool(self.target_id.strip())
    
    def is_verified(self) -> bool:
        """Check if this binding has been verified (test message sent successfully)."""
        return bool(self.verified_at)
    
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RolePushPolicy:
    """Single source of truth for a role's push configuration.
    
    Replaces scattered config in config_json, approval_channels, feishu_open_id, etc.
    One role → one policy object.
    """
    
    agent_code: str
    push_enabled: bool = True  # Global override
    channels: dict[ChannelType, ChannelBinding] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    
    @classmethod
    def default_for_role(cls, agent_code: str) -> RolePushPolicy:
        """Create a default policy (no pushes enabled until configured)."""
        now = datetime.utcnow().isoformat() + "Z"
        return cls(
            agent_code=agent_code,
            push_enabled=False,  # Safest default: require explicit configuration
            channels={},
            created_at=now,
            updated_at=now,
        )
    
    def should_push_to(self, channel: ChannelType) -> bool:
        """Check if role should push to this channel."""
        if not self.push_enabled:
            return False
        binding = self.channels.get(channel)
        if not binding:
            return False
        return binding.is_valid()
    
    def resolve_target(self, channel: ChannelType) -> tuple[str, str] | None:
        """Resolve (target_id, target_type) for this channel.
        
        Returns None if:
            - channel not configured
            - binding not enabled
            - target_id empty
        """
        binding = self.channels.get(channel)
        if not binding or not binding.is_valid():
            return None
        return binding.target_id, binding.target_type
    
    def add_channel(
        self,
        channel: ChannelType,
        target_id: str,
        target_type: str = "",
        enabled: bool = True,
    ) -> None:
        """Configure a channel binding."""
        self.channels[channel] = ChannelBinding(
            channel=channel,
            enabled=enabled,
            target_id=target_id.strip(),
            target_type=target_type.strip(),
            verified_at=None,
        )
        self.updated_at = datetime.utcnow().isoformat() + "Z"
    
    def mark_verified(self, channel: ChannelType) -> None:
        """Mark channel binding as verified (test message succeeded)."""
        binding = self.channels.get(channel)
        if binding:
            binding.verified_at = datetime.utcnow().isoformat() + "Z"
            self.updated_at = binding.verified_at
    
    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for API/logging."""
        return {
            "agent_code": self.agent_code,
            "push_enabled": self.push_enabled,
            "channels": {ch: binding.to_dict() for ch, binding in self.channels.items()},
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
    
    def __repr__(self) -> str:
        enabled_chs = [ch for ch in self.channels if self.channels[ch].is_valid()]
        return f"RolePushPolicy({self.agent_code}, enabled={self.push_enabled}, channels={enabled_chs})"
