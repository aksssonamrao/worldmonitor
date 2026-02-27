from fastapi import APIRouter

from app.domains.planner.service import BriefIn, MitigationIn, agent_brief, agent_mitigation

router = APIRouter(prefix='/api', tags=['agent'])


@router.post('/agent/brief')
async def agent_brief_route(request: BriefIn):
    return await agent_brief(request)


@router.post('/agent/mitigation')
async def agent_mitigation_route(request: MitigationIn):
    return await agent_mitigation(request)
