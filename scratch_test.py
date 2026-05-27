import asyncio
import os
import sys

# Add current directory to path
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from app.db.session import AsyncSessionLocal
from app.modules.search.service import search_food

async def main():
    async with AsyncSessionLocal() as db:
        res = await search_food("Tôi bị dị ứng tôm cua ghẹ, muốn ăn món hải sản, giàu đạm, ăn tối ở Đà Nẵng.", db)
        print("Query:", res.query)
        print("AI response:", res.ai_response)
        for r in res.results:
            print("-", r.name, "score:", r.matchScore, "reason:", r.reason)

if __name__ == "__main__":
    asyncio.run(main())
