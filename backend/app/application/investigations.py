from ..domain.investigations import ReviewBrief
from .ports import InvestigationRepository, WakeupQueue


class InvestigationService:
    def __init__(self, repository: InvestigationRepository, queue: WakeupQueue):
        self.repository, self.queue = repository, queue

    async def start(self, brief: ReviewBrief, owner: str, key: str | None = None):
        job_id = await self.repository.create(brief, owner, key)
        await self.queue.wake(job_id)
        data = await self.get(job_id, owner)
        return {"id": job_id, "status": data["status"]}

    async def get(self, job_id: str, owner: str):
        return await self.repository.get(job_id, owner)

    async def list(self, owner: str, offset=0, limit=20):
        return await self.repository.list(owner, offset, limit)

    async def cancel(self, job_id: str, owner: str):
        await self.get(job_id, owner)
        await self.repository.cancel(job_id, owner)
        await self.queue.wake(job_id)
        data = await self.get(job_id, owner)
        return {"id": job_id, "status": data["status"]}

    async def agent(self, job_id: str, agent_id: str, owner: str):
        data = await self.get(job_id, owner)
        match = next((agent for agent in data["agents"] if agent["id"] == agent_id), None)
        if not match:
            raise LookupError("Agent not found")
        return match

    async def steps(self, job_id: str, agent_id: str, owner: str, offset=0, limit=50):
        await self.agent(job_id, agent_id, owner)
        return await self.repository.steps(job_id, agent_id, offset, limit)

    async def patches(self, job_id: str, owner: str, offset=0, limit=20):
        await self.get(job_id, owner)
        return await self.repository.patches(job_id, offset, limit)

    async def history(self, job_id: str, owner: str, after=0, limit=200, latest=False):
        await self.get(job_id, owner)
        return await self.repository.events(job_id, after, limit, latest)

    async def results(self, job_id: str, owner: str):
        data = await self.get(job_id, owner)
        return {
            "status": data["status"],
            "report": data["report"],
            "agent_results": [
                {"agent_id": agent["id"], "result": agent["result"]}
                for agent in data["agents"]
                if agent["result"]
            ],
        }
