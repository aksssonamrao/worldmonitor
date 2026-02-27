from fastapi import APIRouter

from app.domains.planner.service import PlanRequest, plan

router = APIRouter(prefix='/api', tags=['planner'])


@router.post('/plan')
async def plan_route(request: PlanRequest):
    return await plan(request)
