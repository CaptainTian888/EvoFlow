"""API routes for managing role push bindings."""

from __future__ import annotations

import logging
from typing import Any
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .push_binding_repo import RolePushBindingRepository
from .push_policy import RolePushPolicy, ChannelBinding, ChannelType

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/proactive/push-bindings", tags=["proactive.push"])


class ChannelBindingDTO(BaseModel):
    """DTO for a single channel binding."""
    channel: ChannelType
    enabled: bool = True
    target_id: str = ""
    target_type: str = ""
    verified_at: str | None = None


class RolePushPolicyDTO(BaseModel):
    """DTO for role push policy."""
    agent_code: str
    push_enabled: bool = True
    channels: dict[ChannelType, ChannelBindingDTO] = Field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


@router.get("/roles/{agent_code}")
async def get_role_policy(agent_code: str) -> RolePushPolicyDTO:
    """Get push policy for a role."""
    policy = RolePushBindingRepository.get_policy(agent_code)
    if not policy:
        raise HTTPException(status_code=404, detail=f"No policy found for {agent_code}")
    
    dto = RolePushPolicyDTO(
        agent_code=policy.agent_code,
        push_enabled=policy.push_enabled,
        channels={
            ch: ChannelBindingDTO(
                channel=binding.channel,
                enabled=binding.enabled,
                target_id=binding.target_id,
                target_type=binding.target_type,
                verified_at=binding.verified_at,
            )
            for ch, binding in policy.channels.items()
        },
        created_at=policy.created_at,
        updated_at=policy.updated_at,
    )
    return dto


@router.post("/roles/{agent_code}")
async def update_role_policy(agent_code: str, dto: RolePushPolicyDTO) -> RolePushPolicyDTO:
    """Update push policy for a role."""
    policy = RolePushPolicy(
        agent_code=agent_code,
        push_enabled=dto.push_enabled,
        channels={},
        created_at=dto.created_at,
        updated_at=dto.updated_at,
    )
    
    # Rebuild channels
    for ch, binding_dto in dto.channels.items():
        policy.channels[ch] = ChannelBinding(
            channel=binding_dto.channel,
            enabled=binding_dto.enabled,
            target_id=binding_dto.target_id,
            target_type=binding_dto.target_type,
            verified_at=binding_dto.verified_at,
        )
    
    try:
        RolePushBindingRepository.save_policy(policy)
    except Exception as e:
        logger.error("Failed to update policy for %s: %s", agent_code, e)
        raise HTTPException(status_code=500, detail=str(e))
    
    # Return updated policy
    return await get_role_policy(agent_code)


@router.get("/roles")
async def list_policies(push_enabled: bool | None = Query(None)) -> list[RolePushPolicyDTO]:
    """List all push policies, optionally filtered."""
    policies = RolePushBindingRepository.list_policies()
    
    if push_enabled is not None:
        policies = [p for p in policies if p.push_enabled == push_enabled]
    
    return [
        RolePushPolicyDTO(
            agent_code=p.agent_code,
            push_enabled=p.push_enabled,
            channels={
                ch: ChannelBindingDTO(
                    channel=binding.channel,
                    enabled=binding.enabled,
                    target_id=binding.target_id,
                    target_type=binding.target_type,
                    verified_at=binding.verified_at,
                )
                for ch, binding in p.channels.items()
            },
            created_at=p.created_at,
            updated_at=p.updated_at,
        )
        for p in policies
    ]


@router.put("/roles/{agent_code}/channels/{channel}")
async def add_channel_binding(
    agent_code: str,
    channel: ChannelType,
    target_id: str,
    target_type: str = "",
) -> RolePushPolicyDTO:
    """Add or update a channel binding for a role."""
    policy = RolePushBindingRepository.get_or_create_policy(agent_code)
    policy.add_channel(channel, target_id, target_type, enabled=True)
    
    try:
        RolePushBindingRepository.save_policy(policy)
    except Exception as e:
        logger.error("Failed to add channel binding for %s: %s", agent_code, e)
        raise HTTPException(status_code=500, detail=str(e))
    
    return await get_role_policy(agent_code)


@router.delete("/roles/{agent_code}/channels/{channel}")
async def remove_channel_binding(agent_code: str, channel: ChannelType) -> RolePushPolicyDTO:
    """Remove a channel binding for a role."""
    policy = RolePushBindingRepository.get_policy(agent_code)
    if not policy:
        raise HTTPException(status_code=404, detail=f"No policy found for {agent_code}")
    
    if channel in policy.channels:
        del policy.channels[channel]
    
    try:
        RolePushBindingRepository.save_policy(policy)
    except Exception as e:
        logger.error("Failed to remove channel binding for %s: %s", agent_code, e)
        raise HTTPException(status_code=500, detail=str(e))
    
    return await get_role_policy(agent_code)


@router.post("/roles/{agent_code}/channels/{channel}/verify")
async def verify_channel_binding(agent_code: str, channel: ChannelType) -> dict[str, Any]:
    """Verify a channel binding by sending a test message."""
    policy = RolePushBindingRepository.get_policy(agent_code)
    if not policy:
        raise HTTPException(status_code=404, detail=f"No policy found for {agent_code}")
    
    target = policy.resolve_target(channel)
    if not target:
        raise HTTPException(status_code=400, detail=f"Channel {channel} not configured for {agent_code}")
    
    target_id, target_type = target
    
    try:
        if channel == "feishu":
            from app.channels.service import get_channel_service
            service = get_channel_service()
            if service is None:
                raise HTTPException(status_code=503, detail="Feishu service not available")
            
            # Send test message
            test_msg = f"[Test] Push binding verification for {agent_code}"
            await service.feishu_push_markdown(
                target_id,
                test_msg,
                receive_id_type=target_type,
            )
            
            # Mark as verified
            RolePushBindingRepository.mark_verified(agent_code, channel)
            logger.info("Verified channel binding: %s -> %s", agent_code, channel)
            
            return {"status": "verified", "channel": channel, "agent_code": agent_code}
        else:
            # TODO: implement verification for other channels
            raise HTTPException(status_code=501, detail=f"Verification not implemented for {channel}")
    except Exception as e:
        logger.error("Failed to verify channel binding: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
