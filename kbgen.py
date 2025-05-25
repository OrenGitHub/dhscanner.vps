import httpx
import asyncio

TO_KBGEN_URL = 'http://kbgen:3000/kbgen'

async def kbgen_single(client, one_callable):
    response = await client.post(TO_KBGEN_URL, json=one_callable)
    return response.text

async def kbgen_async(callables):
    async with httpx.AsyncClient() as client:
        tasks = [kbgen_single(client, c) for c in callables]
        responses = await asyncio.gather(*tasks)
    return responses

async def kbgen(callables):
    responses = await kbgen_async(callables)
    # logging.info(f'received {len(callables)} callables')
    return responses